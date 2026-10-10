"""Pipeline: gerar -> verificar modelo -> parse -> contrato -> build -> render -> métricas -> gravar.

Uma tentativa por célula (EXEC@1, sem rodada de correção). Cada falha tem um status próprio:

  api_error / metric_error  falhas de infraestrutura (fora de qualquer análise)
  model_mismatch            o modelo devolvido difere do solicitado (célula refeita; 2ª vez: interrompe)
  refusal / truncated       recusa de segurança / limite de tokens (antes do parser)
  format_failure            nenhum bloco de arquivo válido na resposta
  contract_failure          sem `export class App` em src/app/app.ts
  nonexecutable             o build falhou/estourou o tempo, ou o app-root não renderizou
  done                      executável (as métricas foram calculadas)
"""

import logging
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from specui.codegen import GeneratedBundle, parse_bundle
from specui.config import config_sha256
from specui.harness import (
    BrowserSession,
    ScaffoldHarness,
    StaticServer,
)
from specui.llm import (
    ConfigurationError,
    LLMClient,
    LLMError,
    ModelMismatchError,
    QuotaExceededError,
    make_client,
    model_matches,
)
from specui.metrics.input_spec import compute_input_spec
from specui.metrics.reference import ReferenceUnavailableError, load_reference_blocks
from specui.metrics.technical import compute_cost
from specui.models import (
    Cell,
    ExecMetrics,
    Generator,
    Modality,
    PromptPackage,
    PromptSource,
    RunConfig,
    RunRecord,
    ScaffoldInfo,
    Task,
)
from specui.oracle.provenance import OracleProvenance, freeze_problems, read_provenance
from specui.oracle.requirements import load_pending, load_requirements
from specui.prompting import build_messages
from specui.prompts import resolve_prompt_sources
from specui.stages import MetricStage, StageContext, default_stages, run_stages, stage_technical
from specui.storage import RunStore, make_run_id, repo_commit, short_workspace_id
from specui.tasks import load_tasks

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- planejamento


def _modalities_for(cfg: RunConfig, source: PromptSource) -> list[Modality]:
    if source.kind == "free" and cfg.free_modalities == "intended" and source.intended_modality:
        return [source.intended_modality]
    return list(cfg.modalities)


def plan_cells(cfg: RunConfig, tasks: Sequence[Task], sources: Sequence[PromptSource]) -> list[Cell]:
    """tarefas × fontes × modalidades × geradores × repetições, em ordem REP-MAJOR: se a cota
    acabar no meio, ficam camadas completas (todas as células da repetição 0, depois a 1...)."""
    task_ids = {t.id for t in tasks}
    has_free = any(s.kind == "free" for s in sources)
    max_rep = max(cfg.repetitions, cfg.free_repetitions if has_free else 0)
    cells: list[Cell] = []
    for rep in range(max_rep):
        for source in sources:
            reps = cfg.free_repetitions if source.kind == "free" else cfg.repetitions
            if source.task_id not in task_ids or rep >= reps:
                continue
            for modality in _modalities_for(cfg, source):
                cells.extend(
                    Cell(task_id=source.task_id, prompt_source=source, modality=modality, rep=rep,
                         provider=g.provider, model_id=g.model_id)
                    for g in cfg.generators
                )
    return cells


# --------------------------------------------------------------------------- resumo


class RunSummary(BaseModel):
    total: int = 0
    skipped: int = 0  # já concluídas (retomada)
    not_run: int = 0  # provedor pausado por cota
    by_status: dict[str, int] = Field(default_factory=dict)
    paused_providers: list[str] = Field(default_factory=list)
    quota_messages: list[str] = Field(default_factory=list)

    @property
    def executed(self) -> int:
        return sum(self.by_status.values())


# --------------------------------------------------------------------------- pipeline


class Pipeline:
    def __init__(
        self,
        cfg: RunConfig,
        tasks: Sequence[Task],
        clients: dict[str, LLMClient],
        harness: ScaffoldHarness,
        store: RunStore,
        session: BrowserSession,
        stages: Sequence[MetricStage] | None = None,
        requirements_for: Callable[[str], list[Any]] | None = None,
    ) -> None:
        self.cfg = cfg
        self.tasks = {t.id: t for t in tasks}
        self.generators: dict[str, Generator] = {g.key: g for g in cfg.generators}
        missing = set(self.generators) - set(clients)
        if missing:
            raise ValueError(f"sem cliente para os geradores: {sorted(missing)}")
        self.clients = clients
        self.harness = harness
        self.store = store
        self.session = session
        self.stages = list(stages) if stages is not None else default_stages(cfg)
        self.requirements_for = requirements_for or (lambda task_id: [])
        self.scaffold: ScaffoldInfo = harness.info()
        self.config_sha = config_sha256(cfg)
        self.commit = repo_commit(cfg.repo_root)
        self.oracle = self._read_oracle()

    def _read_oracle(self) -> OracleProvenance | None:
        """Proveniência do oráculo (None sem oracles/ ou fora do git: os testes e o `smoke` seguem)."""
        oracles_dir = self.cfg.path("oracles_dir")
        if not oracles_dir.is_dir():
            return None
        try:
            return read_provenance(self.cfg.repo_root, oracles_dir)
        except (ValueError, OSError):
            return None

    # ------------------------------------------------------------------ uma célula

    def _new_record(self, cell: Cell, gen: Generator, pkg: PromptPackage, task: Task, run_id: str, seed: int | None) -> RunRecord:
        src = cell.prompt_source
        return RunRecord(
            run_id=run_id, run_kind=self.cfg.run_kind, cell_key=cell.key, task_id=task.id,
            difficulty=task.difficulty, prompt_kind=src.kind, prompt_id=src.prompt_id,
            modality=cell.modality, rep=cell.rep, created_at=datetime.now(UTC).isoformat(timespec="seconds"),
            provider=gen.provider, model_id_requested=gen.model_id, temperature=gen.temperature,
            thinking=gen.thinking, seed=seed, prompt_sha256=pkg.prompt_sha256,
            image_sha256=pkg.image_sha256, envelope_sha256=pkg.envelope_sha256,
            envelope_version=pkg.envelope_version, scaffold_version=self.scaffold.version,
            scaffold_lock_sha256=self.scaffold.lock_sha256, scaffold_tree_sha256=self.scaffold.tree_sha256,
            repo_commit=self.commit, config_sha256=self.config_sha, material_shown=src.material_shown,
            **self._provenance_fields(),
        )

    def _provenance_fields(self) -> dict[str, Any]:
        playwright_version, browser_version = self.session.versions()
        fields: dict[str, Any] = {"playwright_version": playwright_version, "browser_version": browser_version}
        if self.oracle is not None:
            fields |= {
                "oracle_suite_tag": self.oracle.tag, "oracle_tree_hash": self.oracle.tree_hash,
                "oracle_content_sha256": self.oracle.content_sha256, "oracle_dirty": self.oracle.dirty,
                "pending_sha256": self.oracle.pending_sha256,
                "mention_patterns_sha256": self.oracle.mention_patterns_sha256,
            }
        return fields

    def run_cell(self, cell: Cell) -> RunRecord:
        """Executa uma célula e grava o record. Cota esgotada e erro de configuração SOBEM
        (não viram record): quem chama decide pausar o provedor ou parar."""
        gen = self.generators[f"{cell.provider}:{cell.model_id}"]
        client, task, source = self.clients[gen.key], self.tasks[cell.task_id], cell.prompt_source
        pkg = build_messages(task, source, cell.modality, self.scaffold)
        seed = self.cfg.base_seed + cell.rep
        run_id = make_run_id(cell)
        out_dir = self.store.run_dir(run_id)
        rec = self._new_record(cell, gen, pkg, task, run_id, seed)
        rec.paths["run_dir"] = str(out_dir)
        rec.input_spec = compute_input_spec(
            source.text, self.requirements_for(task.id), envelope_chars=len(pkg.system)
        )
        (out_dir / "prompt.system.txt").write_text(pkg.system, encoding="utf-8", newline="\n")
        (out_dir / "prompt.user.txt").write_text(pkg.user_text, encoding="utf-8", newline="\n")

        # 1. geração
        try:
            response = client.generate(pkg, seed)
        except LLMError as exc:
            rec.status = "api_error"
            rec.errors.append(str(exc))
            return self._save(rec)
        rec.model_id_returned = response.model_returned
        rec.finish_reason = response.finish_reason  # sempre: OTHER/MALFORMED... viram format_failure e precisam ser distinguíveis
        rec.cost = compute_cost(pkg, response, client)
        (out_dir / "response.raw.txt").write_text(response.text, encoding="utf-8", newline="\n")
        rec.paths["response_raw"] = str(out_dir / "response.raw.txt")

        # 2. o modelo devolvido tem que ser o solicitado
        if not model_matches(gen.model_id, response.model_returned):
            rec.status = "model_mismatch"
            msg = f"modelo solicitado '{gen.model_id}' != devolvido '{response.model_returned}'"
            rec.errors.append(msg)
            logger.warning("ALERTA model_mismatch em %s: %s", cell.key, msg)
            return self._save(rec)

        # 3. recusa e truncamento vêm antes do parser
        if response.refused:
            rec.status = "refusal"
            rec.errors.append(f"recusa: {response.refusal_detail}")
            return self._save(rec)
        if response.truncated:
            rec.status = "truncated"
            rec.errors.append(f"truncado: finish_reason={response.finish_reason}")
            return self._save(rec)

        # 4. formato e contrato
        bundle = parse_bundle(response.text)
        rec.exec = ExecMetrics(
            format_ok=bundle.format_ok, files_accepted=len(bundle.files), files_rejected=bundle.rejected,
        )
        rec.errors.extend(bundle.warnings)
        if not bundle.format_ok:
            rec.status = "format_failure"
            return self._save(rec)
        rec.exec.contract_ok = bundle.contract_ok
        if not bundle.contract_ok:
            rec.status = "contract_failure"
            return self._save(rec)

        # 5. build + render + métricas. Uma falha de INFRAESTRUTURA aqui (disco, porta, Chromium que caiu) não pode perder a
        # chamada paga: vira `metric_error` com a exceção em `errors`, o record é gravado e a retomada não refaz a API
        # (`evaluate --rebuild` refaz só o build/render a partir de response.raw.txt). Falha DO APP (build quebrado, timeout
        # de carregamento) já é `nonexecutable`; erro de configuração e cota continuam subindo.
        try:
            self._build_render_measure(cell, task, pkg, bundle, rec, out_dir)
        except (ConfigurationError, QuotaExceededError):
            raise
        except Exception as exc:
            logger.exception("falha de infraestrutura em %s", cell.key)
            rec.status = "metric_error"
            rec.errors.append(f"infra: {type(exc).__name__}: {exc}")
        return self._save(rec)

    def _build_render_measure(
        self, cell: Cell, task: Task, pkg: PromptPackage, bundle: GeneratedBundle, rec: RunRecord, out_dir: Path
    ) -> None:
        ws_dir = self.harness.prepare_run_dir(short_workspace_id(rec.run_id))
        try:
            self.harness.inject(bundle, ws_dir)
            build = self.harness.build(ws_dir)
            rec.paths.update(self.harness.collect(ws_dir, out_dir, build))
        finally:
            self.harness.cleanup(ws_dir)

        rec.exec.build_ok = build.ok
        rec.exec.build_timed_out = build.timed_out
        rec.exec.build_time_s = build.time_s
        rec.exec.build_stdout_path = rec.paths.get("build_stdout")
        rec.exec.build_stderr_path = rec.paths.get("build_stderr")
        rec.exec.build_error_messages = build.error_messages
        if not build.ok:
            rec.exec.executable = False
            rec.status = "nonexecutable"
            return

        viewport = self.cfg.viewport or task.image_size
        with StaticServer(rec.paths["dist_dir"]) as server:
            render = self.session.capture_initial_render(server.url, viewport, out_dir)
            rec.exec.render_ok = render.render_ok
            rec.exec.executable = render.render_ok
            for key, value in (("screenshot", render.screenshot_path), ("dom_blocks", render.blocks_path),
                               ("css_snapshot", render.css_snapshot_path), ("axe", render.axe_path)):
                if value:
                    rec.paths[key] = value
            rec.errors.extend(render.errors)
            if not render.render_ok:
                rec.status = "nonexecutable"
                return
            ctx = StageContext(
                cfg=self.cfg, task=task, render=render, out_dir=out_dir, record=rec,
                cell=cell, pkg=pkg, bundle=bundle, build=build, url=server.url, session=self.session,
            )
            run_stages(ctx, self.stages)

    def preflight(self) -> None:
        """Falha ANTES de gastar API se faltar a referência do Figma (só com geradores reais:
        execuções só com mock degradam e registram o aviso)."""
        if all(g.provider == "mock" for g in self.cfg.generators):
            return
        self._check_oracle_frozen()
        self._check_oracle_files()
        if not any(s.__name__ == "stage_design2code" for s in self.stages):
            return
        missing = []
        for task in self.tasks.values():
            try:
                load_reference_blocks(task, self.cfg.path("references_dir"), self.cfg.enable_ocr_fallback)
            except ReferenceUnavailableError as exc:
                missing.append(f"{task.id}: {exc}")
        if missing:
            raise ConfigurationError(
                "referência do Figma indisponível (as métricas visuais não poderiam ser calculadas):\n  "
                + "\n  ".join(missing)
            )

    def _check_oracle_files(self) -> None:
        """`requirements.yaml`/`pending.yaml` de cada tarefa precisam carregar ANTES de gastar API: regex inválida em
        `mention_patterns` ou YAML quebrado deixaria a cobertura de requisitos em branco sem aviso (e a nota funcional
        levantaria no mesmo arquivo)."""
        oracles_dir = self.cfg.path("oracles_dir")
        if not oracles_dir.is_dir():
            return
        problems = []
        for task in self.tasks.values():
            for loader in (load_requirements, load_pending):
                try:
                    loader(oracles_dir, task.id)
                except (OSError, ValueError, yaml.YAMLError) as exc:
                    problems.append(f"{task.id}: {loader.__name__.removeprefix('load_')}.yaml: {exc}")
        if problems:
            raise ConfigurationError("arquivos do oráculo inválidos:\n  " + "\n  ".join(problems))

    def _check_oracle_frozen(self) -> None:
        """Execução PRINCIPAL só com o oráculo congelado (tag `oracle-*` na árvore atual, sem mudanças pendentes)."""
        if self.cfg.run_kind != "main" or not any(s.__name__ == "stage_functional" for s in self.stages):
            return
        if self.oracle is None:
            raise ConfigurationError("oracles/ não encontrado: a nota funcional não pode ser calculada")
        problems = freeze_problems(self.oracle)
        if problems:
            raise ConfigurationError("o oráculo não está congelado:\n  " + "\n  ".join(problems))

    def _save(self, rec: RunRecord) -> RunRecord:
        _relativize_paths(rec, self.store.root)
        self.store.save(rec)
        return rec

    # ------------------------------------------------------------------ o experimento

    def run(
        self,
        cells: Sequence[Cell],
        resume: bool = True,
        on_result: Callable[[int, int, Cell, RunRecord | None], None] | None = None,
    ) -> RunSummary:
        """Executa as células com retomada. Cota esgotada pausa SÓ aquele provedor; a mesma
        divergência de modelo duas vezes na mesma célula interrompe tudo (ModelMismatchError)."""
        done = self.store.completed_keys() if resume else set()
        summary = RunSummary(total=len(cells))
        paused: set[str] = set()
        mismatches: Counter[str] = Counter()
        providers = {c.provider for c in cells}

        for i, cell in enumerate(cells, start=1):
            if cell.key in done:
                summary.skipped += 1
                continue
            if cell.provider in paused:
                summary.not_run += 1
                continue
            while True:
                try:
                    rec = self.run_cell(cell)
                except QuotaExceededError as exc:
                    paused.add(cell.provider)
                    summary.paused_providers.append(cell.provider)
                    summary.quota_messages.append(str(exc))
                    summary.not_run += 1
                    if on_result:
                        on_result(i, len(cells), cell, None)
                    break
                if rec.status == "model_mismatch":
                    mismatches[cell.key] += 1
                    if mismatches[cell.key] >= 2:
                        raise ModelMismatchError(
                            f"divergência de modelo repetida em {cell.key}: {rec.errors[-1]}. "
                            "Run interrompido para investigação (checkpoint intacto)."
                        )
                    continue  # refaz a célula imediatamente
                summary.by_status[rec.status] = summary.by_status.get(rec.status, 0) + 1
                if on_result:
                    on_result(i, len(cells), cell, rec)
                break
            if providers and providers <= paused:
                logger.warning("todos os provedores pausados por cota; encerrando")
                break
        return summary


def _relativize_paths(rec: RunRecord, root: Path) -> None:
    """Grava os caminhos relativos (`run_dir` à raiz dos resultados; os artefatos à pasta da
    execução): o record continua válido se results/ for movido ou exportado."""
    base = Path(rec.paths["run_dir"]) if "run_dir" in rec.paths else None
    if base is None:
        return

    def rel(value: str | None) -> str | None:
        if not value:
            return value
        try:
            return Path(value).relative_to(base).as_posix()
        except ValueError:
            return value

    rec.paths = {k: (v if k == "run_dir" else rel(v) or v) for k, v in rec.paths.items()}
    rec.paths["run_dir"] = base.relative_to(root).as_posix()
    rec.exec.build_stdout_path = rel(rec.exec.build_stdout_path)
    rec.exec.build_stderr_path = rel(rec.exec.build_stderr_path)
    if rec.technical:
        rec.technical.axe_report_path = rel(rec.technical.axe_report_path)
    if rec.design2code:
        rec.design2code.pairs_path = rel(rec.design2code.pairs_path)


# --------------------------------------------------------------------------- montagem


def _requirements_loader(cfg: RunConfig) -> Callable[[str], list[Any]]:
    """Requisitos da tarefa (alimentam `mention_patterns` em `InputSpecMetrics`). Sem a pasta oracles/ (testes, `smoke` em
    repositório fictício) a cobertura fica vazia; com a pasta, um arquivo inválido NÃO é engolido (o `preflight` já o recusou)."""
    cache: dict[str, list[Any]] = {}

    def load(task_id: str) -> list[Any]:
        if task_id not in cache:
            oracles_dir = cfg.path("oracles_dir")
            cache[task_id] = load_requirements(oracles_dir, task_id) if oracles_dir.is_dir() else []
        return cache[task_id]

    return load


def build_pipeline(
    cfg: RunConfig,
    clients: dict[str, LLMClient] | None = None,
    session: BrowserSession | None = None,
) -> tuple[Pipeline, list[Cell]]:
    """Carrega tarefas e fontes, cria clientes/harness/store e planeja as células."""
    tasks = load_tasks(cfg.path("benchmarks_dir"), list(cfg.tasks))
    sources = resolve_prompt_sources(cfg, tasks)
    clients = clients or {g.key: make_client(g) for g in cfg.generators}
    harness = ScaffoldHarness(
        cfg.path("scaffold_dir"), cfg.path("workspace_dir"), cfg.build_timeout_s, cfg.build_configuration
    )
    session = session or BrowserSession(cfg.clock_epoch_iso, cfg.render_settle_ms, cfg.block_network)
    store = RunStore(cfg.path("results_dir"), cfg.run_kind)
    pipeline = Pipeline(cfg, tasks, clients, harness, store, session, requirements_for=_requirements_loader(cfg))
    return pipeline, plan_cells(cfg, tasks, sources)


def run_experiment(
    cfg: RunConfig,
    resume: bool = True,
    on_result: Callable[[int, int, Cell, RunRecord | None], None] | None = None,
) -> RunSummary:
    pipeline, cells = build_pipeline(cfg)
    pipeline.preflight()
    if cfg.run_kind == "main":
        try:
            pipeline.store.freeze_meta(cfg.analysis.equivalence_margin, pipeline.config_sha)
        except ValueError as exc:
            raise ConfigurationError(str(exc)) from exc
    with pipeline.session:
        return pipeline.run(cells, resume=resume, on_result=on_result)


__all__ = ["MetricStage", "Pipeline", "RunSummary", "StageContext", "build_pipeline", "plan_cells", "run_experiment", "stage_technical"]
