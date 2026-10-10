"""Linha de comando: `specui <comando>`."""

import shutil
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from specui.clock import fixed_date_br
from specui.config import find_repo_root, load_config
from specui.harness import BrowserSession, ScaffoldHarness
from specui.llm import ConfigurationError, ModelMismatchError, make_client, model_matches
from specui.models import Cell, Generator, RunConfig, RunRecord
from specui.oracle.provenance import freeze_problems, read_provenance
from specui.pipeline import RunSummary, run_experiment
from specui.storage import RunStore
from specui.tasks import png_size

for _stream in (sys.stdout, sys.stderr):  # acentos corretos em consoles Windows (cp1252)
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

app = typer.Typer(no_args_is_help=True, add_completion=False, help="SPEC-UI: avaliação automática de front-end gerado por LLMs.")
console = Console()

ConfigOpt = Annotated[Path, typer.Option("--config", "-c", help="YAML da configuração (aceita `extends:`).")]
DEFAULT_CONFIG = Path("configs/default.yaml")


def _csv(value: str | None) -> list[str] | None:
    return [v.strip() for v in value.split(",") if v.strip()] if value else None


def _resolve_config(path: Path) -> Path:
    if path.is_absolute() or path.exists():
        return path
    candidate = find_repo_root(Path(__file__)) / path
    return candidate if candidate.exists() else path


def _load(config: Path, overrides: dict | None = None) -> RunConfig:
    try:
        return load_config(_resolve_config(config), overrides=overrides)
    except (OSError, ValueError) as exc:
        console.print(f"[red]Configuração inválida:[/red] {exc}")
        raise typer.Exit(2) from exc


def _mock_generator(variant: str) -> Generator:
    return Generator(provider="mock", model_id="mock-1", mock_variant=variant, request_delay_s=0)  # type: ignore[arg-type]


def _as_smoke(cfg: RunConfig) -> RunConfig:
    """O gerador simulado nunca grava em results/ (principal) nem em results/pilot/: vai para results/smoke/."""
    if cfg.run_kind != "smoke":
        console.print(f"[yellow]gerador simulado: gravando em results/smoke/ (e não em {cfg.run_kind})[/yellow]")
    return cfg.model_copy(update={"run_kind": "smoke"})


def _print_summary(summary: RunSummary) -> None:
    table = Table(title="Resumo da execução")
    table.add_column("status")
    table.add_column("células", justify="right")
    for status, n in sorted(summary.by_status.items()):
        table.add_row(status, str(n))
    console.print(table)
    console.print(
        f"total planejado: {summary.total} | executadas: {summary.executed} | "
        f"já concluídas (retomada): {summary.skipped} | não executadas: {summary.not_run}"
    )
    for provider, message in zip(summary.paused_providers, summary.quota_messages, strict=False):
        console.print(f"[yellow]Cota esgotada em {provider}:[/yellow] {message}")
    if summary.not_run:
        console.print("Progresso salvo. Rode o mesmo comando de novo para continuar de onde parou.")


def _reporter(i: int, n: int, cell: Cell, rec: RunRecord | None) -> None:
    label = "[yellow]pausada (cota)[/yellow]" if rec is None else rec.status
    console.print(f"[{i}/{n}] {cell.key} -> {label}")


def _execute(cfg: RunConfig, resume: bool) -> RunSummary:
    console.print(
        f"run_kind={cfg.run_kind} | geradores: {', '.join(g.key for g in cfg.generators)} | "
        f"fontes: {', '.join(cfg.prompt_sources)} | repetições: {cfg.repetitions}"
    )
    try:
        summary = run_experiment(cfg, resume=resume, on_result=_reporter)
    except ModelMismatchError as exc:
        console.print(f"[red bold]INTERROMPIDO:[/red bold] {exc}")
        raise typer.Exit(2) from exc
    except ConfigurationError as exc:
        console.print(f"[red bold]Erro de configuração:[/red bold] {exc}")
        raise typer.Exit(2) from exc
    _print_summary(summary)
    return summary


@app.command()
def run(
    config: ConfigOpt = DEFAULT_CONFIG,
    reps: Annotated[int | None, typer.Option(help="Repetições por célula (sobrescreve o YAML).")] = None,
    tasks: Annotated[str | None, typer.Option(help="Dificuldades, ex.: easy,medium.")] = None,
    modalities: Annotated[str | None, typer.Option(help="text,multimodal")] = None,
    prompt_sources: Annotated[str | None, typer.Option(help="no_spec,with_spec,free:<coleta>")] = None,
    generators: Annotated[str | None, typer.Option(help="Filtra por provedor, ex.: google")] = None,
    run_kind: Annotated[str | None, typer.Option(help="main | pilot")] = None,
    mock: Annotated[bool, typer.Option(help="Usa o gerador simulado (sem API).")] = False,
    mock_variant: Annotated[str, typer.Option(help="Com --mock: ok|broken|no_format|no_contract|truncated|refusal|model_mismatch")] = "ok",
    resume: Annotated[bool, typer.Option(help="Pula células já concluídas.")] = True,
) -> None:
    """Executa o experimento (com retomada pelo manifest)."""
    overrides: dict = {}
    if reps:
        overrides["repetitions"] = reps
    for key, value in (("tasks", tasks), ("modalities", modalities), ("prompt_sources", prompt_sources)):
        if _csv(value):
            overrides[key] = _csv(value)
    if run_kind:
        overrides["run_kind"] = run_kind
    cfg = _load(config, overrides)
    wanted = _csv(generators)
    if wanted:
        kept = [g for g in cfg.generators if g.provider in wanted]
        if not kept:
            console.print(f"[red]Nenhum gerador com provider em {wanted}[/red]")
            raise typer.Exit(2)
        cfg = cfg.model_copy(update={"generators": kept})
    if mock:
        cfg = _as_smoke(cfg).model_copy(update={"generators": [_mock_generator(mock_variant)]})
    _execute(cfg, resume)


@app.command()
def pilot(
    config: ConfigOpt = Path("configs/pilot.yaml"),
    mock: Annotated[bool, typer.Option(help="Usa o gerador simulado (sem API).")] = False,
) -> None:
    """Piloto: 1 repetição, todos os geradores, grava em results/pilot/ (fora da análise)."""
    cfg = _load(config)
    if mock:
        cfg = _as_smoke(cfg).model_copy(update={"generators": [_mock_generator("ok")]})
    _execute(cfg, resume=True)


@app.command()
def smoke(config: ConfigOpt = DEFAULT_CONFIG) -> None:
    """Fumaça ponta a ponta com o gerador simulado: 1 tarefa, 1 célula, em results/smoke/ (fora do piloto e da análise)."""
    overrides = {"run_kind": "smoke", "repetitions": 1, "tasks": ["easy"], "modalities": ["text"],
                 "prompt_sources": ["no_spec"]}
    cfg = _load(config, overrides).model_copy(update={"generators": [_mock_generator("ok")]})
    summary = _execute(cfg, resume=False)

    from specui.tasks import load_tasks

    frame_size = load_tasks(cfg.path("benchmarks_dir"), ["easy"])[0].image_size  # o frame da tarefa, não um 1440x900 fixo
    store = RunStore(cfg.path("results_dir"), "smoke")
    rec = store.load_records()[-1] if store.load_records() else None
    checks: list[tuple[str, bool]] = []
    if rec:
        shot = store.artifact(rec, "screenshot") if "screenshot" in rec.paths else Path("")
        checks = [
            ("status == done", rec.status == "done"),
            ("executável", rec.exec.executable is True),
            ("screenshot no tamanho do frame do Figma", shot.is_file() and png_size(shot) == frame_size),
            ("métricas técnicas presentes", rec.technical is not None),
            ("métricas do insumo presentes", rec.input_spec is not None),
            ("record.json gravado", (store.root / rec.paths["run_dir"] / "record.json").is_file()),
        ]
    ok = bool(rec) and all(passed for _, passed in checks) and summary.by_status.get("done") == 1
    for name, passed in checks:
        console.print(f"  {'[green]OK[/green]' if passed else '[red]FALHOU[/red]'}  {name}")
    console.print("[green bold]smoke OK[/green bold]" if ok else "[red bold]smoke FALHOU[/red bold]")
    raise typer.Exit(0 if ok else 1)


@app.command("check-model")
def check_model(config: ConfigOpt = DEFAULT_CONFIG) -> None:
    """Confirma que cada modelo configurado existe e imprime o id/versão devolvidos pela API."""
    cfg = _load(config)
    table = Table(title="check-model")
    for col in ("gerador", "solicitado", "devolvido pela API", "confere"):
        table.add_column(col)
    bad = False
    for gen in cfg.generators:
        try:
            returned = make_client(gen).check_model()
            match = model_matches(gen.model_id, returned)
        except ConfigurationError as exc:
            returned, match = f"ERRO: {exc}", False
        bad = bad or not match
        table.add_row(gen.key, gen.model_id, returned, "[green]sim[/green]" if match else "[red]NÃO[/red]")
    console.print(table)
    raise typer.Exit(1 if bad else 0)


@app.command("scaffold-check")
def scaffold_check(config: ConfigOpt = DEFAULT_CONFIG) -> None:
    """Verifica Node/npm, instala o node_modules compartilhado e constrói o scaffold vazio."""
    cfg = _load(config)
    for tool in ("node", "npm"):
        path = shutil.which(tool)
        version = subprocess.run([path, "--version"], capture_output=True, text=True, check=False).stdout.strip() if path else "AUSENTE"
        console.print(f"{tool}: {version}")
    harness = ScaffoldHarness(cfg.path("scaffold_dir"), cfg.path("workspace_dir"), cfg.build_timeout_s, cfg.build_configuration)
    info = harness.info()
    console.print(f"scaffold {info.version} | Angular {info.angular_version} | lock {info.lock_sha256[:12]} | árvore {str(info.tree_sha256)[:12]}")
    for name, version in info.packages.items():
        console.print(f"  {name}@{version}")
    console.print("Instalando/verificando node_modules compartilhado (a primeira vez demora)...")
    result = harness.verify_pristine()
    if result.ok:
        console.print(f"[green bold]scaffold OK[/green bold] (build do projeto vazio em {result.time_s}s)")
        raise typer.Exit(0)
    console.print("[red bold]build do scaffold FALHOU[/red bold]")
    for msg in result.error_messages:
        console.print(f"  {msg}")
    raise typer.Exit(1)


@app.command()
def evaluate(
    config: ConfigOpt = DEFAULT_CONFIG,
    run_id: Annotated[str | None, typer.Option(help="Reavalia só esta execução.")] = None,
    all_runs: Annotated[bool, typer.Option("--all", help="Reavalia todas as execuções renderizadas.")] = False,
    groups: Annotated[str | None, typer.Option(help="Grupos: technical,visual,code,functional (padrão: todos).")] = None,
    run_kind: Annotated[str | None, typer.Option(help="main | pilot (padrão: o da config).")] = None,
    include_mock: Annotated[bool, typer.Option("--include-mock", help="Inclui runs do gerador simulado (por padrão ficam de fora).")] = False,
) -> None:
    """Recalcula métricas a partir dos artefatos gravados, SEM chamar o LLM nem refazer o build."""
    from specui.stages import reevaluate_record
    from specui.tasks import load_tasks

    if not run_id and not all_runs:
        console.print("[red]Informe --run-id <id> ou --all.[/red]")
        raise typer.Exit(2)
    cfg = _load(config, {"run_kind": run_kind} if run_kind else None)
    wanted = _csv(groups)
    if cfg.run_kind == "main" and (wanted is None or "functional" in wanted):
        # reavaliar a nota funcional de uma execução PRINCIPAL é medir com o oráculo: ele precisa estar congelado
        problems = freeze_problems(read_provenance(cfg.repo_root, cfg.path("oracles_dir")))
        if problems:
            console.print("[red bold]evaluate recusado:[/red bold] o oráculo não está congelado:")
            for message in problems:
                console.print(f"  {message}")
            raise typer.Exit(2)
    store = RunStore(cfg.path("results_dir"), cfg.run_kind)
    tasks = {t.id: t for t in load_tasks(cfg.path("benchmarks_dir"))}
    records = [r for r in store.load_records() if (all_runs or r.run_id == run_id) and (include_mock or r.provider != "mock")]
    if not records:
        console.print("[yellow]Nenhuma execução encontrada.[/yellow]")
        raise typer.Exit(1)
    failed = 0
    with ExitStack() as stack:
        needs_browser = wanted is None or "functional" in wanted  # o oráculo precisa do navegador
        session = (
            stack.enter_context(BrowserSession(cfg.clock_epoch_iso, cfg.render_settle_ms, cfg.block_network))
            if needs_browser else None
        )
        for rec in records:
            if rec.status not in ("done", "metric_error"):
                console.print(f"  pulada  {rec.run_id} (status {rec.status}: sem render)")
                continue
            try:
                reevaluate_record(cfg, store.root, rec, tasks[rec.task_id], wanted, session=session)
            except (ValueError, OSError) as exc:
                console.print(f"  [red]erro[/red]   {rec.run_id}: {exc}")
                failed += 1
                continue
            store.save(rec)
            console.print(f"  {rec.status:13s} {rec.run_id}")
    raise typer.Exit(1 if failed else 0)


# ----------------------------------------------------------------------------- oráculos


def _suites(cfg: RunConfig, only: str | None = None) -> list[str]:
    root = cfg.path("oracles_dir")
    names = sorted(p.name for p in root.iterdir() if p.is_dir() and (p / "requirements.yaml").is_file()) if root.is_dir() else []
    return [n for n in names if only is None or n == only]


@app.command("oracle-lint")
def oracle_lint(config: ConfigOpt = DEFAULT_CONFIG, task: Annotated[str | None, typer.Option(help="Só esta tarefa.")] = None) -> None:
    """Confere a autoria das suítes (sem seletor frágil, caso sem asserção, requisitos e pendências existentes)."""
    from specui.oracle import lint_suite, load_suite

    cfg = _load(config)
    problems = 0
    for name in _suites(cfg, task):
        found = lint_suite(load_suite(cfg.path("oracles_dir"), name), cfg.path("oracles_dir"))
        console.print(f"{'[red]✗[/red]' if found else '[green]✓[/green]'} {name}: {len(found)} problema(s)")
        for message in found:
            console.print(f"    {message}")
        problems += len(found)
    raise typer.Exit(1 if problems else 0)


@app.command("oracle-matrix")
def oracle_matrix(config: ConfigOpt = DEFAULT_CONFIG, task: Annotated[str | None, typer.Option(help="Só esta tarefa.")] = None) -> None:
    """Gera oracles/<tarefa>/traceability.md (requisito × caso) e falha se um requisito testável ficar sem caso."""
    from specui.oracle import build_traceability, load_suite
    from specui.oracle.requirements import load_requirements

    cfg = _load(config)
    oracles = cfg.path("oracles_dir")
    problems = 0
    for name in _suites(cfg, task):
        markdown, found = build_traceability(load_suite(oracles, name), load_requirements(oracles, name))
        (oracles / name / "traceability.md").write_text(markdown, encoding="utf-8", newline="\n")
        console.print(f"{'[red]✗[/red]' if found else '[green]✓[/green]'} {name}: traceability.md ({len(found)} problema(s))")
        for message in found:
            console.print(f"    {message}")
        problems += len(found)
    raise typer.Exit(1 if problems else 0)


@app.command("pilot-report")
def pilot_report(config: ConfigOpt = Path("configs/pilot.yaml")) -> None:
    """Gera results/pilot/failure_report.{md,csv}: taxas por modelo e cada caso que não deu YES, para classificar."""
    from specui.pilot_report import write_pilot_report

    cfg = _load(config, {"run_kind": "pilot"})
    try:
        paths = write_pilot_report(cfg.path("results_dir"))
    except FileNotFoundError as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        raise typer.Exit(1) from exc
    for name, path in paths.items():
        console.print(f"  {name}: {path}")


@app.command()
def serve(
    run_id: Annotated[str, typer.Option(help="Execução cujo app será aberto (o dist/ gravado).")],
    config: ConfigOpt = DEFAULT_CONFIG,
    run_kind: Annotated[str, typer.Option(help="pilot | main")] = "pilot",
    port: Annotated[int, typer.Option(help="Porta local (0 = qualquer livre).")] = 0,
) -> None:
    """Serve o app gerado de uma execução no navegador, para conferir à mão o que o oráculo apontou (Ctrl+C encerra)."""
    import time
    import webbrowser

    from specui.harness import StaticServer

    cfg = _load(config, {"run_kind": run_kind})
    store = RunStore(cfg.path("results_dir"), run_kind)  # type: ignore[arg-type]
    rec = next((r for r in store.load_records() if r.run_id == run_id), None)
    if rec is None:
        console.print(f"[red]Execução {run_id} não encontrada em {store.root}[/red]")
        raise typer.Exit(1)
    dist = store.root / rec.paths["run_dir"] / rec.paths.get("dist_dir", "dist")
    if not dist.is_dir():
        console.print(f"[red]{run_id} não tem dist/ (status {rec.status}: o app não foi construído).[/red]")
        raise typer.Exit(1)
    with StaticServer(dist, port=port) as server:
        console.print(f"App de {run_id} em [bold]{server.url}[/bold]  (Ctrl+C para encerrar)")
        console.print(f"Obs.: o oráculo roda com o relógio fixo em {fixed_date_br()}; aqui o relógio é o real.")
        webbrowser.open(server.url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            console.print("encerrado")

@app.command()
def mutate(
    config: ConfigOpt = Path("configs/pilot.yaml"),
    pilot_run: Annotated[str, typer.Option("--pilot-run", help="run_id do piloto (ou `all` para todas as `done`).")] = "all",
) -> None:
    """Mutação em tempo de execução sobre saídas do piloto que deram YES: o oráculo percebe o app quebrado?"""
    from specui.oracle import load_suite
    from specui.oracle.mutations import (
        run_mutations_with_baseline,
        summarize,
        write_baseline,
        write_sensitivity,
    )
    from specui.tasks import load_tasks

    cfg = _load(config, {"run_kind": "pilot"})
    store = RunStore(cfg.path("results_dir"), "pilot")
    tasks = {t.id: t for t in load_tasks(cfg.path("benchmarks_dir"))}
    records = [r for r in store.load_records()
               if r.status == "done" and r.provider != "mock" and (pilot_run == "all" or r.run_id == pilot_run)]
    if not records:
        console.print("[yellow]Nenhuma execução `done` do piloto encontrada.[/yellow]")
        raise typer.Exit(1)
    rows, baseline_rows = [], []
    with BrowserSession(cfg.clock_epoch_iso, cfg.render_settle_ms, cfg.block_network) as session:
        for rec in records:
            dist = store.root / rec.paths["run_dir"] / rec.paths.get("dist_dir", "dist")
            if not dist.is_dir():
                console.print(f"  pulada {rec.run_id}: sem dist/")
                continue
            suite = load_suite(cfg.path("oracles_dir"), rec.task_id)
            viewport = cfg.viewport or tasks[rec.task_id].image_size
            run_rows, run_baseline = run_mutations_with_baseline(suite, session, dist, viewport, rec.run_id, block_network=cfg.block_network)
            rows += run_rows
            baseline_rows += run_baseline
            console.print(f"  {rec.run_id}: {len(rows)} linhas acumuladas")
    out = write_sensitivity(rows, store.root / "sensitivity.csv")
    baseline_out = write_baseline(baseline_rows, store.root / "sensitivity_baseline.csv")
    not_applied = [r for r in rows if r.verdict == "NOT_APPLIED"]
    for r in not_applied:  # todo NOT_APPLIED vem com o diagnóstico do baseline
        console.print(f"[yellow]NOT_APPLIED[/yellow] {r.mutation_id} × {r.case_id} em {r.run_id}: {r.detail}")
    table = Table(title="Sensibilidade por caso")
    for column in ("caso", "KILLED", "WEAK", "SURVIVED", "NOT_APPLIED"):
        table.add_column(column)
    for case_id, counts in sorted(summarize(rows).items()):
        table.add_row(case_id, *(str(counts.get(v, 0)) for v in ("KILLED", "WEAK", "SURVIVED", "NOT_APPLIED")))
    console.print(table)
    console.print(f"[green]{out}[/green]  (casos com SURVIVED precisam ser revistos antes do congelamento)")
    console.print(f"[green]{baseline_out}[/green]  (baseline de cada caso-alvo: outcome, bloqueio, asserções que falharam, erro)")


# ----------------------------------------------------------------------------- prompts livres, análise, export

prompts_app = typer.Typer(no_args_is_help=True, help="Prompts livres de participantes.")
app.add_typer(prompts_app, name="prompts")


@prompts_app.command("import")
def prompts_import(
    collection: Annotated[str, typer.Option(help="Id da coleta (pasta em benchmarks/free_prompts/).")],
    file: Annotated[Path, typer.Option(help="CSV exportado do formulário (fica em private/).")],
    map_file: Annotated[Path, typer.Option("--map", help="YAML com o mapeamento de colunas e as faixas de perfil.")],
    config: ConfigOpt = DEFAULT_CONFIG,
    dry_run: Annotated[bool, typer.Option(help="Só valida e mostra o resumo; não grava.")] = False,
) -> None:
    """Importa respostas do formulário (anônimo): remove PII, lista as remoções e grava prompts.jsonl."""
    from specui.prompts import import_free_prompts
    from specui.tasks import load_tasks

    cfg = _load(config)
    directory = cfg.path("benchmarks_dir") / "free_prompts" / collection
    valid = {t.id for t in load_tasks(cfg.path("benchmarks_dir"))}
    try:
        result = import_free_prompts(directory, file, map_file, valid, write=not dry_run)
    except (OSError, ValueError) as exc:
        console.print(f"[red]Importação recusada:[/red] {exc}")
        raise typer.Exit(1) from exc
    console.print(f"aceitos: {len(result.accepted)} | rejeitados: {len(result.rejected)} | remoções de PII: {len(result.redactions)}")
    if not dry_run:
        console.print(f"Revise {directory / 'import_report.md'} antes de rodar `--prompt-sources free:{collection}`.")


@app.command()
def analyze(config: ConfigOpt = DEFAULT_CONFIG) -> None:
    """Contraste principal (ITT) por modelo, condicional, consistência, itens e livres → results/aggregate/report.md."""
    from specui.analysis import AnalysisRefused
    from specui.analysis.report import run_analysis

    cfg = _load(config, {"run_kind": "main"})
    try:
        paths = run_analysis(cfg)
    except AnalysisRefused as exc:
        console.print(f"[red bold]Análise recusada:[/red bold] {exc}")
        raise typer.Exit(1) from exc
    for name, path in paths.items():
        console.print(f"  {name}: {path}")


@app.command()
def export(
    out: Annotated[Path, typer.Option(help="Zip de saída, ex.: export/specui-2026-11-01.zip")],
    config: ConfigOpt = DEFAULT_CONFIG,
) -> None:
    """(Opcional) Empacota results/ da execução principal para depósito com DOI. Nunca inclui o piloto."""
    from specui.export import export_results

    cfg = _load(config, {"run_kind": "main"})
    try:
        path = export_results(cfg.path("results_dir"), out)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    console.print(f"[green]{path}[/green]")


@app.command("figma-derive")
def figma_derive(config: ConfigOpt = DEFAULT_CONFIG) -> None:
    """Deriva references/figma/blocks.json de nodes.raw.json (offline; sem chamar a API do Figma)."""
    from specui.metrics.reference import ReferenceUnavailableError, derive_all

    cfg = _load(config)
    tasks_dir = cfg.path("benchmarks_dir") / "tasks"
    refs = cfg.path("references_dir")
    try:
        derived = derive_all(tasks_dir / "figma_frames.yaml", refs / "nodes.raw.json", refs / "blocks.json", tasks_dir)
    except (ReferenceUnavailableError, OSError) as exc:
        console.print(f"[red]Falhou:[/red] {exc}")
        raise typer.Exit(1) from exc
    for task_id, entry in derived.items():
        console.print(f"  {task_id}: {len(entry['blocks'])} blocos de texto")
    console.print(f"[green]{refs / 'blocks.json'}[/green]")


if __name__ == "__main__":
    app()
