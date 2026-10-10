import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from specui.cli import app

runner = CliRunner()


@pytest.fixture
def mock_config(repo_root, tmp_path) -> Path:
    """Config mínima em um repositório fictício (o pyproject.toml marca a raiz)."""
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    cfg = tmp_path / "mock.yaml"
    cfg.write_text(
        f"extends: {(repo_root / 'configs' / 'default.yaml').as_posix()}\n"
        "generators:\n  - {provider: mock, model_id: mock-1, request_delay_s: 0}\n",
        encoding="utf-8",
    )
    return cfg


def test_help_lists_the_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("run", "pilot", "smoke", "check-model", "scaffold-check"):
        assert command in result.output


def test_check_model_ok_with_mock(mock_config):
    result = runner.invoke(app, ["check-model", "--config", str(mock_config)])
    assert result.exit_code == 0, result.output
    assert "mock-1" in result.output and "sim" in result.output


def test_check_model_fails_without_api_key(repo_root, monkeypatch):
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    for i in range(1, 10):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
    monkeypatch.setattr("specui.config._ENV_LOADED", True)  # não recarrega o .env real
    result = runner.invoke(app, ["check-model", "--config", str(repo_root / "configs" / "default.yaml")])
    assert result.exit_code == 1
    assert "NÃO" in result.output and "GEMINI_API_KEY" in result.output  # sem mock silencioso


def test_invalid_config_exits_with_code_2(tmp_path):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    bad = tmp_path / "bad.yaml"
    bad.write_text("repetitions: 0\ngenerators: []\n", encoding="utf-8")
    result = runner.invoke(app, ["run", "--config", str(bad), "--mock"])
    assert result.exit_code == 2
    assert "inválida" in result.output


# ----------------------------------------------------------------------------- oráculo, análise, export


def test_oracle_lint_and_matrix_on_the_real_suites(repo_root, tmp_path):
    """Roda sobre uma CÓPIA de oracles/: `oracle-matrix` grava traceability.md e o teste não pode escrever na árvore do repositório."""
    import shutil

    copy = tmp_path / "oracles"
    shutil.copytree(repo_root / "oracles", copy, ignore=shutil.ignore_patterns("__pycache__"))
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    config = tmp_path / "copy.yaml"
    config.write_text(os.linesep.join([f"extends: {(repo_root / 'configs' / 'default.yaml').as_posix()}",
                                       f"oracles_dir: {copy.as_posix()}"]) + os.linesep, encoding="utf-8")
    assert runner.invoke(app, ["oracle-lint", "--config", str(config)]).exit_code == 0
    result = runner.invoke(app, ["oracle-matrix", "--config", str(config), "--task", "easy_pomodoro"])
    assert result.exit_code == 0 and "easy_pomodoro" in result.output
    text = (copy / "easy_pomodoro" / "traceability.md").read_text(encoding="utf-8")
    assert "| E-01 |" in text and "E-A-10 (pendente)" in text
    # o gerado a partir da cópia é idêntico ao commitado: o traceability.md versionado está em dia
    committed = (repo_root / "oracles" / "easy_pomodoro" / "traceability.md").read_text(encoding="utf-8")
    assert text.split() == committed.split()  # sem diferenças de conteúdo (a quebra de linha do checkout não conta)


def test_analyze_refuses_without_main_runs(mock_config):
    result = runner.invoke(app, ["analyze", "--config", str(mock_config)])
    assert result.exit_code == 1 and "recusada" in result.output


def test_export_zip_has_manifest_and_skips_the_pilot(tmp_path):
    import json
    import zipfile

    from specui.export import export_results

    results = tmp_path / "results"
    run = results / "runs" / "r1"
    (run / "generated" / "src" / "app").mkdir(parents=True)
    (run / "dist").mkdir()
    (run / "record.json").write_text("{}", encoding="utf-8")
    (run / "generated" / "src" / "app" / "app.ts").write_text("export class App {}", encoding="utf-8")
    (run / "dist" / "main.js").write_text("x", encoding="utf-8")
    (results / "pilot" / "runs" / "p1").mkdir(parents=True)
    (results / "pilot" / "runs" / "p1" / "record.json").write_text("{}", encoding="utf-8")
    out = export_results(results, tmp_path / "out" / "pkg.zip")
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        manifest = json.loads(zf.read("MANIFEST.json"))
    assert names == {"runs/r1/record.json", "runs/r1/generated/src/app/app.ts", "MANIFEST.json"}  # sem dist/ e sem piloto
    assert set(manifest["files"]) == names - {"MANIFEST.json"} and all(len(h) == 64 for h in manifest["files"].values())
    with pytest.raises(FileNotFoundError):
        export_results(tmp_path / "vazio", tmp_path / "x.zip")


def test_pilot_report_lists_failures_and_rates(repo_root, tmp_path):
    from specui.models import CaseOutcome, FunctionalMetrics, RunRecord
    from specui.pilot_report import write_pilot_report
    from specui.storage import RunStore

    store = RunStore(tmp_path, "pilot")
    for i, (status, cases) in enumerate([("done", [("E-A-01", "YES"), ("E-A-02", "PARTIAL")]), ("contract_failure", [])]):
        rec = RunRecord(run_id=f"r{i}", run_kind="pilot", cell_key=f"k{i}", task_id="easy_pomodoro", difficulty="easy",
                        prompt_kind="no_spec", prompt_id="easy_pomodoro/no_spec", modality="text", rep=0,
                        created_at="2026-10-09T00:00:00+00:00", provider="google", model_id_requested="g",
                        prompt_sha256="p", envelope_sha256="e", envelope_version="2", status=status,
                        paths={"run_dir": f"runs/r{i}"})
        rec.exec.format_ok, rec.exec.contract_ok = True, status == "done"
        if cases:
            rec.functional = FunctionalMetrics(accuracy_a=0.75, cases=[
                CaseOutcome(case_id=c, level="A", outcome=o, failed=["x :: y"] if o != "YES" else []) for c, o in cases])
        store.save(rec)
    paths = write_pilot_report(tmp_path)
    md = paths["markdown"].read_text(encoding="utf-8")
    assert "E-A-02" in md and "E-A-01" not in md.split("## Casos")[1]  # só o que não deu YES
    assert "contract_failure" in md and "specui serve --run-id r0" in md
    rows = paths["csv"].read_text(encoding="utf-8-sig").splitlines()
    assert rows[0].split(";")[-2:] == ["classification", "note"] and len(rows) == 3


def _dirty_oracle(monkeypatch):
    from specui.oracle.provenance import OracleProvenance

    monkeypatch.setattr("specui.cli.read_provenance", lambda *a, **k: OracleProvenance(
        tag=None, tree_hash="t", dirty=True, content_sha256="c", pending_sha256="p", mention_patterns_sha256="m", version_file="oracle-v1"))


def test_evaluate_functional_on_a_main_run_requires_a_frozen_oracle(mock_config, monkeypatch):
    _dirty_oracle(monkeypatch)
    refused = runner.invoke(app, ["evaluate", "--all", "--run-kind", "main", "--groups", "functional", "--config", str(mock_config)])
    assert refused.exit_code == 2 and "não está congelado" in refused.output and "não commitadas" in refused.output
    everything = runner.invoke(app, ["evaluate", "--all", "--run-kind", "main", "--config", str(mock_config)])  # sem --groups = todos
    assert everything.exit_code == 2 and "não está congelado" in everything.output
    # outros grupos, e o piloto, não exigem o oráculo congelado: passam pela checagem (o repositório fictício não tem tarefas,
    # então falham adiante por outro motivo, nunca com o exit 2 da recusa)
    visual = runner.invoke(app, ["evaluate", "--all", "--run-kind", "main", "--groups", "visual", "--config", str(mock_config)])
    pilot = runner.invoke(app, ["evaluate", "--all", "--run-kind", "pilot", "--groups", "functional", "--config", str(mock_config)])
    for result in (visual, pilot):
        assert result.exit_code != 2 and "não está congelado" not in result.output


def test_mock_generator_never_writes_to_main_or_pilot(mock_config, tmp_path, monkeypatch):
    """`run --mock` e `pilot --mock` (config de main/pilot) gravam em results/smoke/, não no resultado real."""
    seen = []

    def fake_execute(cfg, resume):
        seen.append((cfg.run_kind, [g.provider for g in cfg.generators]))
        from specui.pipeline import RunSummary

        return RunSummary()

    monkeypatch.setattr("specui.cli._execute", fake_execute)
    runner.invoke(app, ["run", "--mock", "--config", str(mock_config)])
    runner.invoke(app, ["pilot", "--mock", "--config", str(mock_config)])
    assert seen == [("smoke", ["mock"]), ("smoke", ["mock"])]


def test_evaluate_skips_mock_runs_unless_asked(repo_root, mock_config):
    from specui.models import RunRecord
    from specui.storage import RunStore

    root = mock_config.parent
    config = root / "eval.yaml"
    lines = [
        f"extends: {(repo_root / 'configs' / 'default.yaml').as_posix()}",
        f"benchmarks_dir: {(repo_root / 'benchmarks').as_posix()}",
        f"results_dir: {(root / 'results').as_posix()}",
        "generators:",
        "  - {provider: mock, model_id: mock-1, request_delay_s: 0}",
    ]
    config.write_text(os.linesep.join(lines) + os.linesep, encoding="utf-8")
    store = RunStore(root / "results", "pilot")
    for i, provider in enumerate(("mock", "google")):
        store.save(RunRecord(run_id=f"r{i}", run_kind="pilot", cell_key=f"k{i}", task_id="easy_pomodoro", difficulty="easy",
                             prompt_kind="no_spec", prompt_id="easy_pomodoro/no_spec", modality="text", rep=0,
                             created_at="2026-10-09T00:00:00+00:00", provider=provider, model_id_requested="m",
                             prompt_sha256="p", envelope_sha256="e", envelope_version="2", status="format_failure",
                             paths={"run_dir": f"runs/r{i}"}))
    ignored = runner.invoke(app, ["evaluate", "--run-id", "r0", "--run-kind", "pilot", "--groups", "visual", "--config", str(config)])
    assert ignored.exit_code == 1 and "Nenhuma execução" in ignored.output  # o record do mock é ignorado
    included = runner.invoke(app, ["evaluate", "--run-id", "r0", "--run-kind", "pilot", "--groups", "visual", "--include-mock", "--config", str(config)])
    assert "Nenhuma execução" not in included.output and "sem render" in included.output  # com --include-mock ele entra
