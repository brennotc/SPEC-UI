"""Pipeline com harness e navegador falsos (rápido, sem Node nem Chromium)."""

import shutil
from pathlib import Path

import pytest

from specui.codegen import GeneratedBundle
from specui.config import load_config
from specui.harness import BuildResult, RenderArtifacts
from specui.llm import (
    ConfigurationError,
    DailyQuotaExceededError,
    LLMError,
    LLMResponse,
    MockClient,
    ModelMismatchError,
)
from specui.models import Generator, ScaffoldInfo
from specui.pipeline import Pipeline, plan_cells, stage_technical
from specui.prompts import resolve_prompt_sources
from specui.storage import RunStore

PNG_1X1 = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
           b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x9a\x9a\x9a\x00\x00\x00\x00IEND\xaeB`\x82")


class FakeHarness:
    """Mesma interface do ScaffoldHarness, sem Node."""

    def __init__(self, root: Path, build_ok: bool = True, timed_out: bool = False) -> None:
        self.root, self.build_ok, self.timed_out = root, build_ok, timed_out
        self.prepared: list[str] = []
        self.injected: list[GeneratedBundle] = []
        self.cleaned: list[Path] = []

    def info(self) -> ScaffoldInfo:
        return ScaffoldInfo(version="t", lock_sha256="l" * 64, tree_sha256="t" * 64, angular_version="20.0.0",
                            packages={"@angular/core": "20.0.0"})

    def prepare_run_dir(self, run_id: str) -> Path:
        self.prepared.append(run_id)
        d = self.root / run_id
        (d / "src" / "app").mkdir(parents=True)
        return d

    def inject(self, bundle: GeneratedBundle, run_dir: Path) -> list[str]:
        self.injected.append(bundle)
        for f in bundle.files:
            (run_dir / f.path).parent.mkdir(parents=True, exist_ok=True)
            (run_dir / f.path).write_text(f.content, encoding="utf-8")
        return [f.path for f in bundle.files]

    def build(self, run_dir: Path) -> BuildResult:
        out, err = self.root / f"{run_dir.name}.out", self.root / f"{run_dir.name}.err"
        out.write_text("build", encoding="utf-8")
        err.write_text("", encoding="utf-8")
        if self.build_ok:
            (run_dir / "dist" / "app").mkdir(parents=True)
            (run_dir / "dist" / "app" / "index.html").write_text("<app-root></app-root>", encoding="utf-8")
        return BuildResult(
            ok=self.build_ok and not self.timed_out, timed_out=self.timed_out, time_s=1.5,
            return_code=0 if self.build_ok else 1, stdout_path=str(out), stderr_path=str(err),
            error_messages=[] if self.build_ok else ["NG8001: erro de build"],
            dist_dir=str(run_dir / "dist" / "app") if self.build_ok else None,
        )

    def collect(self, run_dir: Path, dest: Path, build: BuildResult, keep_dist: bool = True) -> dict[str, str]:
        shutil.copytree(run_dir / "src" / "app", dest / "generated" / "src" / "app", dirs_exist_ok=True)
        paths = {"generated_dir": str(dest / "generated")}
        if build.dist_dir:
            shutil.copytree(build.dist_dir, dest / "dist", dirs_exist_ok=True)
            paths["dist_dir"] = str(dest / "dist")
        for key, src in (("build_stdout", build.stdout_path), ("build_stderr", build.stderr_path)):
            shutil.copyfile(src, dest / f"{key}.txt")
            paths[key] = str(dest / f"{key}.txt")
        return paths

    def cleanup(self, run_dir: Path) -> None:
        self.cleaned.append(run_dir)
        shutil.rmtree(run_dir, ignore_errors=True)


class FakeSession:
    def __init__(self, render_ok: bool = True) -> None:
        self.render_ok, self.calls = render_ok, []

    def versions(self) -> tuple[str | None, str | None]:
        return "1.0-test", "chromium-test"

    def capture_initial_render(self, url: str, viewport: tuple[int, int], out_dir: Path) -> RenderArtifacts:
        self.calls.append((url, viewport))
        shot = Path(out_dir) / "screenshot.png"
        shot.write_bytes(PNG_1X1)
        return RenderArtifacts(render_ok=self.render_ok, viewport=viewport, screenshot_path=str(shot),
                               console_errors=["boom"], axe_violations={"critical": 0})


class ScriptedClient:
    """Cliente que devolve (ou levanta) o que estiver no roteiro, uma entrada por chamada."""

    def __init__(self, script: list, model: str = "m-1") -> None:
        self.script, self.model, self.calls = list(script), model, 0

    def generate(self, pkg, seed):
        self.calls += 1
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    def count_tokens(self, system, user_text):
        return 10

    def check_model(self):
        return self.model


GOOD = MockClient(Generator(provider="mock", model_id="m-1"))


def good_response(model: str = "m-1") -> LLMResponse:
    dummy = type("P", (), {"system": "s", "user_text": "u"})()
    return GOOD.generate(dummy, 1).model_copy(update={"model_returned": model})


@pytest.fixture
def make_cfg(repo_root, tmp_path):
    def _make(generators=None, **overrides):
        cfg = load_config(repo_root / "configs" / "default.yaml",
                          overrides={"results_dir": str(tmp_path / "results"), "repetitions": 2,
                                     "enable_embeddings": False, **overrides})
        gens = generators or [Generator(provider="mock", model_id="m-1", request_delay_s=0)]
        return cfg.model_copy(update={"generators": gens})
    return _make


@pytest.fixture
def make_pipeline(tasks, tmp_path, make_cfg):
    def _make(clients=None, cfg=None, harness=None, session=None, stages=None):
        cfg = cfg or make_cfg()
        clients = clients or {g.key: MockClient(g) for g in cfg.generators}
        harness = harness or FakeHarness(tmp_path / "ws")
        session = session or FakeSession()
        store = RunStore(cfg.path("results_dir"), cfg.run_kind)
        stages = [stage_technical] if stages is None else stages  # testes rápidos: sem modelos pesados
        pipeline = Pipeline(cfg, tasks, clients, harness, store, session, stages=stages)
        sources = resolve_prompt_sources(cfg, tasks)
        return pipeline, plan_cells(cfg, tasks, sources), harness, session
    return _make


# ----------------------------------------------------------------------- plan_cells


def test_plan_cells_counts_and_rep_major_order(repo_root, tasks, tmp_path):
    cfg = load_config(repo_root / "configs" / "default.yaml", overrides={"results_dir": str(tmp_path)})
    cells = plan_cells(cfg, tasks, resolve_prompt_sources(cfg, tasks))
    assert len(cells) == 3 * 2 * 2 * 1 * 5  # tarefas × fontes × modalidades × geradores × reps
    assert len({c.key for c in cells}) == len(cells)
    assert [c.rep for c in cells[:12]] == [0] * 12  # camada completa antes da repetição seguinte
    assert {c.rep for c in cells[12:24]} == {1}
    assert {(c.provider, c.model_id) for c in cells} == {("google", "gemini-3.8-flash")}


def test_plan_cells_free_prompts_use_intended_modality_and_own_reps(make_cfg, tasks):
    from specui.models import PromptSource

    def free(pid, modality):
        return PromptSource(kind="free", prompt_id=pid, task_id="easy_pomodoro", text="t", text_sha256="h",
                            intended_modality=modality)

    cfg = make_cfg(repetitions=2, free_repetitions=3)
    sources = [free("free:c/p001/1", "text"), free("free:c/p002/1", None)]
    cells = plan_cells(cfg, tasks, sources)
    by_source: dict[str, list] = {}
    for c in cells:
        by_source.setdefault(c.prompt_source.prompt_id, []).append(c)
    assert {c.modality for c in by_source["free:c/p001/1"]} == {"text"}  # a intenção do participante
    assert {c.modality for c in by_source["free:c/p002/1"]} == {"text", "multimodal"}  # sem intenção: ambas
    assert max(c.rep for c in cells) == 2 and len(by_source["free:c/p001/1"]) == 3
    both = plan_cells(make_cfg(free_modalities="both"), tasks, sources[:1])
    assert {c.modality for c in both} == {"text", "multimodal"}


# ----------------------------------------------------------------------- run_cell


def test_run_cell_done_records_everything_and_relative_paths(make_pipeline, tmp_path):
    pipeline, cells, harness, session = make_pipeline(stages=[stage_technical])
    rec = pipeline.run_cell(cells[0])
    assert rec.status == "done"
    assert rec.exec.format_ok and rec.exec.contract_ok and rec.exec.build_ok and rec.exec.render_ok
    assert rec.exec.executable is True and rec.exec.build_time_s == 1.5
    assert rec.technical.console_errors == ["boom"] and rec.technical.console_error_count == 1
    assert rec.model_id_requested == rec.model_id_returned == "m-1"
    assert rec.seed == pipeline.cfg.base_seed + cells[0].rep
    assert rec.input_spec and rec.cost.prompt_tokens and rec.cost.output_tokens
    assert rec.config_sha256 and rec.scaffold_version == "t" and rec.scaffold_tree_sha256 == "t" * 64
    # caminhos relativos: o run_dir à raiz dos resultados, os artefatos ao run_dir
    assert rec.paths["run_dir"] == f"runs/{rec.run_id}"
    assert all(not Path(v).is_absolute() for v in rec.paths.values())
    assert pipeline.store.artifact(rec, "screenshot").is_file()
    assert pipeline.store.artifact(rec, "dist_dir").is_dir()
    assert (pipeline.store.root / "runs" / rec.run_id / "record.json").is_file()
    assert session.calls[0][1] == (1440, 900)  # viewport = tamanho do PNG do Figma
    assert len(harness.cleaned) == 1 and not harness.cleaned[0].exists()
    assert len(harness.prepared[0]) == 11  # id curto no workspace (MAX_PATH)


def test_no_spec_and_with_spec_send_different_text(make_pipeline, tasks):
    pipeline, cells, *_ = make_pipeline()
    by_kind = {c.prompt_source.kind: c for c in cells if c.rep == 0 and c.task_id == "easy_pomodoro" and c.modality == "text"}
    a, b = pipeline.run_cell(by_kind["no_spec"]), pipeline.run_cell(by_kind["with_spec"])
    assert a.prompt_sha256 != b.prompt_sha256 and a.envelope_sha256 == b.envelope_sha256
    assert a.input_spec.chars < b.input_spec.chars


@pytest.mark.parametrize(
    "variant, status, built",
    [
        ("no_format", "format_failure", False),
        ("no_contract", "contract_failure", False),
        ("truncated", "truncated", False),
        ("refusal", "refusal", False),
    ],
)
def test_early_failures_never_reach_the_build(make_cfg, make_pipeline, variant, status, built):
    gens = [Generator(provider="mock", model_id="m-1", mock_variant=variant, request_delay_s=0)]
    pipeline, cells, harness, session = make_pipeline(cfg=make_cfg(gens))
    rec = pipeline.run_cell(cells[0])
    assert rec.status == status
    assert harness.prepared == [] and session.calls == []
    assert rec.exec.executable is None  # só é definido quando formato E contrato passam
    if status == "contract_failure":
        assert rec.exec.format_ok and rec.exec.contract_ok is False
    if status == "format_failure":
        assert not rec.exec.format_ok and rec.exec.contract_ok is None


def test_build_failure_is_nonexecutable_with_messages(make_pipeline, tmp_path):
    pipeline, cells, *_ = make_pipeline(harness=FakeHarness(tmp_path / "ws", build_ok=False))
    rec = pipeline.run_cell(cells[0])
    assert rec.status == "nonexecutable" and rec.exec.executable is False and rec.exec.build_ok is False
    assert rec.exec.build_error_messages == ["NG8001: erro de build"]
    assert rec.technical is None and rec.exec.render_ok is None  # nada a renderizar


def test_build_timeout_is_nonexecutable(make_pipeline, tmp_path):
    pipeline, cells, *_ = make_pipeline(harness=FakeHarness(tmp_path / "ws", build_ok=True, timed_out=True))
    rec = pipeline.run_cell(cells[0])
    assert rec.status == "nonexecutable" and rec.exec.build_timed_out is True


def test_render_failure_is_nonexecutable(make_pipeline):
    pipeline, cells, *_ = make_pipeline(session=FakeSession(render_ok=False))
    rec = pipeline.run_cell(cells[0])
    assert rec.status == "nonexecutable" and rec.exec.render_ok is False and rec.exec.executable is False
    assert rec.technical is None


def test_metric_stage_exception_becomes_metric_error(make_pipeline):
    def boom(ctx):
        raise RuntimeError("métrica quebrou")

    pipeline, cells, *_ = make_pipeline(stages=[boom, stage_technical])
    rec = pipeline.run_cell(cells[0])
    assert rec.status == "metric_error"
    assert any("boom" in e and "métrica quebrou" in e for e in rec.errors)
    assert rec.technical is not None  # os demais estágios continuam
    assert rec.exec.executable is True  # a geração em si foi válida


def test_api_error_is_recorded_and_not_completed(make_cfg, make_pipeline):
    cfg = make_cfg()
    client = ScriptedClient([LLMError("falha 500")])
    pipeline, cells, *_ = make_pipeline(cfg=cfg, clients={cfg.generators[0].key: client})
    rec = pipeline.run_cell(cells[0])
    assert rec.status == "api_error" and "falha 500" in rec.errors[0]
    assert cells[0].key not in pipeline.store.completed_keys()


def test_quota_and_configuration_errors_bubble_up(make_cfg, make_pipeline):
    cfg = make_cfg()
    pipeline, cells, *_ = make_pipeline(cfg=cfg, clients={cfg.generators[0].key: ScriptedClient(
        [DailyQuotaExceededError("acabou", provider="google")])})
    with pytest.raises(DailyQuotaExceededError):
        pipeline.run_cell(cells[0])
    assert pipeline.store.manifest() == []  # nada gravado: a célula continua pendente


# ----------------------------------------------------------------------- run: retomada e cotas


def test_run_resumes_and_skips_completed(make_pipeline):
    pipeline, cells, *_ = make_pipeline()
    cells = cells[:4]
    first = pipeline.run(cells)
    assert first.executed == 4 and first.skipped == 0 and first.by_status == {"done": 4}
    second = pipeline.run(cells)
    assert second.executed == 0 and second.skipped == 4
    third = pipeline.run(cells, resume=False)
    assert third.executed == 4


def test_api_error_cells_are_redone_on_next_run(make_cfg, make_pipeline):
    cfg = make_cfg()
    key = cfg.generators[0].key
    client = ScriptedClient([LLMError("x"), good_response(), good_response()])
    pipeline, cells, *_ = make_pipeline(cfg=cfg, clients={key: client})
    cells = cells[:2]
    s1 = pipeline.run(cells)
    assert s1.by_status == {"api_error": 1, "done": 1}
    s2 = pipeline.run(cells)
    assert s2.executed == 1 and s2.skipped == 1 and s2.by_status == {"done": 1}


def test_quota_pauses_only_that_provider_and_continues(make_cfg, make_pipeline):
    gens = [Generator(provider="google", model_id="g-1", request_delay_s=0),
            Generator(provider="mock", model_id="a-1", request_delay_s=0)]
    cfg = make_cfg(gens, repetitions=2)
    clients = {
        "google:g-1": ScriptedClient([good_response("g-1"), DailyQuotaExceededError("fim do dia", provider="google")], "g-1"),
        "mock:a-1": ScriptedClient([good_response("a-1")] * 20, "a-1"),
    }
    pipeline, cells, *_ = make_pipeline(cfg=cfg, clients=clients)
    cells = cells[:8]
    seen = []
    summary = pipeline.run(cells, on_result=lambda i, n, c, r: seen.append((c.provider, r and r.status)))
    assert summary.paused_providers == ["google"] and "fim do dia" in summary.quota_messages[0]
    assert summary.by_status["done"] == 1 + 4  # 1 do google antes da cota + todas as do outro provedor
    assert summary.not_run == 3  # as demais do google não rodaram
    assert ("google", None) in seen
    assert clients["google:g-1"].calls == 2  # depois da cota, o google nem é chamado


def test_all_providers_exhausted_stops_the_run(make_cfg, make_pipeline):
    cfg = make_cfg()
    key = cfg.generators[0].key
    client = ScriptedClient([DailyQuotaExceededError("sem crédito", provider="mock")])
    pipeline, cells, *_ = make_pipeline(cfg=cfg, clients={key: client})
    summary = pipeline.run(cells[:5])
    assert summary.executed == 0 and client.calls == 1 and summary.paused_providers == ["mock"]
    assert summary.not_run == 5 and summary.total == 5  # a que bateu na cota + as 4 que nem foram tentadas


def test_model_mismatch_first_time_is_redone(make_cfg, make_pipeline):
    cfg = make_cfg()
    key = cfg.generators[0].key
    client = ScriptedClient([good_response("outro-modelo"), good_response("m-1")])
    pipeline, cells, *_ = make_pipeline(cfg=cfg, clients={key: client})
    summary = pipeline.run(cells[:1])
    assert summary.by_status == {"done": 1} and client.calls == 2
    statuses = [e["status"] for e in pipeline.store.manifest()]
    assert statuses == ["model_mismatch", "done"]  # a tentativa divergente fica registrada
    assert pipeline.store.completed_keys() == {cells[0].key}
    run_ids = [e["run_id"] for e in pipeline.store.manifest()]
    assert len(set(run_ids)) == 2  # duas tentativas imediatas, dois run_id, dois record.json (a divergente não é sobrescrita)
    assert all((pipeline.store.runs_dir / rid / "record.json").is_file() for rid in run_ids)


def test_model_mismatch_twice_aborts_the_run(make_cfg, make_pipeline):
    cfg = make_cfg()
    key = cfg.generators[0].key
    client = ScriptedClient([good_response("outro")] * 2)
    pipeline, cells, *_ = make_pipeline(cfg=cfg, clients={key: client})
    with pytest.raises(ModelMismatchError, match="interrompido"):
        pipeline.run(cells[:3])
    assert [e["status"] for e in pipeline.store.manifest()] == ["model_mismatch", "model_mismatch"]
    assert pipeline.store.completed_keys() == set()  # checkpoint intacto: nada concluído por engano


def test_gemini_version_suffix_is_not_a_mismatch(make_cfg, make_pipeline):
    cfg = make_cfg()
    key = cfg.generators[0].key
    pipeline, cells, *_ = make_pipeline(cfg=cfg, clients={key: ScriptedClient([good_response("m-1-001")])})
    assert pipeline.run(cells[:1]).by_status == {"done": 1}


def test_pipeline_requires_a_client_per_generator(make_cfg, make_pipeline):
    cfg = make_cfg()
    with pytest.raises(ValueError, match="sem cliente"):
        make_pipeline(cfg=cfg, clients={"google:x": ScriptedClient([])})


def test_pilot_records_go_under_results_pilot(make_cfg, make_pipeline, tmp_path):
    pipeline, cells, *_ = make_pipeline(cfg=make_cfg(run_kind="pilot"))
    rec = pipeline.run_cell(cells[0])
    assert rec.run_kind == "pilot"
    assert (tmp_path / "results" / "pilot" / "runs" / rec.run_id / "record.json").is_file()
    assert not (tmp_path / "results" / "runs").exists()


# ----------------------------------------------------------------------- congelamento do oráculo e proveniência


def test_main_run_with_real_generators_refuses_an_unfrozen_oracle(make_cfg, make_pipeline):
    from specui.oracle.provenance import OracleProvenance
    from specui.stages import stage_functional

    real = [Generator(provider="google", model_id="gemini-2.5-flash", request_delay_s=0)]
    cfg = make_cfg(generators=real)
    pipeline, *_ = make_pipeline(cfg=cfg, clients={real[0].key: MockClient(real[0])}, stages=[stage_functional])
    pipeline.oracle = OracleProvenance(tag=None, tree_hash="t", dirty=True, content_sha256="c", pending_sha256="p",
                                       mention_patterns_sha256="m", version_file="oracle-v1")
    with pytest.raises(ConfigurationError, match="não está congelado") as err:
        pipeline.preflight()
    assert "não commitadas" in str(err.value) and "git tag oracle-v1" in str(err.value)

    pipeline.oracle = OracleProvenance(tag="oracle-v1", tree_hash="t", dirty=False, content_sha256="c", pending_sha256="p",
                                       mention_patterns_sha256="m", version_file="oracle-v1")
    pipeline._check_oracle_frozen()  # congelado: passa
    pilot_pipeline, *_ = make_pipeline(cfg=make_cfg(generators=real, run_kind="pilot"),
                                       clients={real[0].key: MockClient(real[0])}, stages=[stage_functional])
    pilot_pipeline.oracle = None
    pilot_pipeline._check_oracle_frozen()  # o piloto não exige congelamento


def test_records_carry_oracle_provenance_and_browser_versions(make_pipeline, make_cfg):
    from specui.oracle.provenance import OracleProvenance

    pipeline, cells, *_ = make_pipeline()
    pipeline.oracle = OracleProvenance(tag="oracle-v1", tree_hash="tree", dirty=False, content_sha256="content",
                                       pending_sha256="pend", mention_patterns_sha256="mention", version_file="oracle-v1")
    rec = pipeline.run_cell(cells[0])
    assert (rec.oracle_suite_tag, rec.oracle_tree_hash, rec.oracle_content_sha256) == ("oracle-v1", "tree", "content")
    assert (rec.oracle_dirty, rec.pending_sha256, rec.mention_patterns_sha256) == (False, "pend", "mention")
    assert (rec.playwright_version, rec.browser_version) == ("1.0-test", "chromium-test")


# ----------------------------------------------------------------------- falha de infraestrutura no build/render (B1)


class BrokenHarness(FakeHarness):
    """Falha uma vez ao preparar a pasta de build (disco, junction) e depois funciona."""

    def __init__(self, root, error: Exception, times: int = 1) -> None:
        super().__init__(root)
        self.error, self.times = error, times

    def prepare_run_dir(self, run_id):
        if self.times > 0:
            self.times -= 1
            raise self.error
        return super().prepare_run_dir(run_id)


class CrashingSession(FakeSession):
    def capture_initial_render(self, url, viewport, out_dir):
        raise RuntimeError("TargetClosedError: o Chromium fechou")


def test_infrastructure_failure_in_build_becomes_a_saved_metric_error(make_cfg, make_pipeline, tmp_path):
    cfg = make_cfg()
    key = cfg.generators[0].key
    client = ScriptedClient([good_response()] * 4)
    harness = BrokenHarness(tmp_path / "ws", OSError("disco cheio"))
    pipeline, cells, *_ = make_pipeline(cfg=cfg, clients={key: client}, harness=harness)
    summary = pipeline.run(cells[:2])  # a 1ª célula perde o build; o run SEGUE para a 2ª
    assert summary.by_status == {"metric_error": 1, "done": 1}
    first = pipeline.store.load_records()[0]
    assert first.status == "metric_error" and any("infra: OSError: disco cheio" in e for e in first.errors)
    assert (pipeline.store.runs_dir / first.run_id / "response.raw.txt").is_file()  # a resposta paga está no disco
    assert len(pipeline.store.manifest()) == 2 and client.calls == 2
    pipeline.run(cells[:2])  # retomada: metric_error conta como concluída, não gasta API de novo
    assert client.calls == 2


def test_chromium_crash_in_render_is_a_metric_error_too(make_cfg, make_pipeline):
    cfg = make_cfg()
    pipeline, cells, *_ = make_pipeline(cfg=cfg, session=CrashingSession())
    rec = pipeline.run_cell(cells[0])
    assert rec.status == "metric_error" and any("infra: RuntimeError: TargetClosedError" in e for e in rec.errors)
    assert pipeline.store.manifest()[-1]["status"] == "metric_error"


def test_configuration_errors_from_the_harness_still_stop_the_run(make_cfg, make_pipeline, tmp_path):
    pipeline, cells, *_ = make_pipeline(harness=BrokenHarness(tmp_path / "ws", ConfigurationError("npm não encontrado")))
    with pytest.raises(ConfigurationError, match="npm"):
        pipeline.run_cell(cells[0])  # o pesquisador precisa corrigir o ambiente: não vira metric_error


def test_finish_reason_is_recorded_for_every_generation(make_cfg, make_pipeline):
    cfg = make_cfg()
    key = cfg.generators[0].key
    refusal = good_response().model_copy(update={"text": "", "refused": True, "finish_reason": "RECITATION", "refusal_detail": "RECITATION"})
    odd = good_response().model_copy(update={"text": "sem blocos de arquivo", "finish_reason": "OTHER"})
    truncated = good_response().model_copy(update={"truncated": True, "finish_reason": "MAX_TOKENS"})
    pipeline, cells, *_ = make_pipeline(cfg=cfg, clients={key: ScriptedClient([good_response(), refusal, odd, truncated])})
    records = [pipeline.run_cell(c) for c in cells[:4]]
    assert [(r.status, r.finish_reason) for r in records] == [
        ("done", "STOP"), ("refusal", "RECITATION"), ("format_failure", "OTHER"), ("truncated", "MAX_TOKENS")]


def test_preflight_refuses_invalid_oracle_files_before_any_api_call(make_cfg, make_pipeline, tmp_path):
    oracles = tmp_path / "oracles"
    for task in ("easy_pomodoro", "medium_tarefas", "hard_kanban"):
        (oracles / task).mkdir(parents=True)
        (oracles / task / "requirements.yaml").write_text(
            "requirements:\n  - {id: X-1, text: t, category: a, info_source: image}\n", encoding="utf-8")
    (oracles / "medium_tarefas" / "requirements.yaml").write_text(
        "requirements:\n  - {id: X-1, text: t, category: a, info_source: image, mention_patterns: ['(']}\n", encoding="utf-8")  # regex inválida
    (oracles / "hard_kanban" / "pending.yaml").write_text("pending: [quebrado\n", encoding="utf-8")  # YAML inválido
    real = [Generator(provider="google", model_id="gemini-3.8-flash", request_delay_s=0)]
    cfg = make_cfg(generators=real, oracles_dir=str(oracles), run_kind="pilot")
    pipeline, *_ = make_pipeline(cfg=cfg, clients={real[0].key: MockClient(real[0])}, stages=[stage_technical])
    with pytest.raises(ConfigurationError, match="arquivos do oráculo inválidos") as err:
        pipeline.preflight()
    text = str(err.value)
    assert "medium_tarefas: requirements.yaml" in text and "mention_pattern" in text and "hard_kanban: pending.yaml" in text
    assert "easy_pomodoro" not in text  # o arquivo válido não é acusado
    (oracles / "medium_tarefas" / "requirements.yaml").write_text("requirements:\n  - {id: X-1, text: t, category: a, info_source: image}\n", encoding="utf-8")
    (oracles / "hard_kanban" / "pending.yaml").write_text("pending: []\n", encoding="utf-8")
    pipeline.preflight()  # corrigidos: passa


def test_preflight_refuses_missing_embedding_models_before_any_api_call(make_cfg, make_pipeline, tmp_path, monkeypatch):
    from specui.metrics import embeddings as emb
    from specui.stages import stage_embeddings

    monkeypatch.setattr(emb, "embeddings_available", lambda: (True, None))
    real = [Generator(provider="google", model_id="gemini-3.8-flash", request_delay_s=0)]
    cfg = make_cfg(generators=real, run_kind="pilot", enable_embeddings=True, model_cache_dir=str(tmp_path / "cache"))
    pipeline, *_ = make_pipeline(cfg=cfg, clients={real[0].key: MockClient(real[0])}, stages=[stage_embeddings])
    monkeypatch.setattr(pipeline, "_check_oracle_files", lambda: None)
    with pytest.raises(ConfigurationError, match="facebook/dinov2-base") as err:
        pipeline.preflight()
    assert str(tmp_path / "cache") in str(err.value)
    monkeypatch.setattr(emb, "ensure_cached", lambda cache: {})  # modelos no cache: passa (a referência do Figma é outro item)
    monkeypatch.setattr("specui.pipeline.load_reference_blocks", lambda *a, **k: None)
    pipeline.preflight()


def test_requirements_loader_no_longer_swallows_invalid_files(make_cfg, tmp_path):
    from specui.pipeline import _requirements_loader

    oracles = tmp_path / "oracles"
    (oracles / "easy_pomodoro").mkdir(parents=True)
    (oracles / "easy_pomodoro" / "requirements.yaml").write_text(
        "requirements:\n  - {id: X, text: t, category: a, info_source: image, mention_patterns: ['(']}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="mention_pattern"):
        _requirements_loader(make_cfg(oracles_dir=str(oracles)))("easy_pomodoro")
    assert _requirements_loader(make_cfg(oracles_dir=str(tmp_path / "nao-existe")))("easy_pomodoro") == []  # sem pasta: vazio
