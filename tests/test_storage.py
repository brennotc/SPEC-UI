import json
from datetime import UTC, datetime

import pandas as pd

from specui.models import Cell, ExecMetrics, FunctionalMetrics, RunRecord, TechnicalMetrics
from specui.prompts import make_standard_source
from specui.storage import (
    RunStore,
    flatten_record,
    make_run_id,
    records_to_dataframe,
    short_workspace_id,
    to_long,
    write_aggregate,
)


def _cell(tasks, kind="no_spec", rep=0, provider="google", modality="text"):
    return Cell(task_id=tasks[0].id, prompt_source=make_standard_source(tasks[0], kind),
                modality=modality, rep=rep, provider=provider, model_id="m-1")


def _record(cell, run_id, status="done", **kw):
    return RunRecord(
        run_id=run_id, run_kind="main", cell_key=cell.key, task_id=cell.task_id, difficulty="easy",
        prompt_kind=cell.prompt_source.kind, prompt_id=cell.prompt_source.prompt_id,
        modality=cell.modality, rep=cell.rep, created_at="2026-10-09T00:00:00+00:00",
        provider=cell.provider, model_id_requested="m-1", prompt_sha256="p", envelope_sha256="e",
        envelope_version="2", status=status, paths={"run_dir": f"runs/{run_id}"}, **kw,
    )


def test_run_id_is_filesystem_safe_and_unique_per_attempt(tasks):
    cell = Cell(task_id="x", prompt_source=make_standard_source(tasks[0], "with_spec"),
                modality="multimodal", rep=3, provider="google", model_id="m")
    a = make_run_id(cell, datetime(2026, 10, 9, 14, 30, 5, tzinfo=UTC))
    b = make_run_id(cell, datetime(2026, 10, 9, 14, 30, 6, tzinfo=UTC))
    assert a == "easy_pomodoro-with_spec__multimodal__google__r3__20261009T143005000000"
    assert a != b and all(c.isalnum() or c in "_.-" for c in a)
    same_second = datetime(2026, 10, 9, 14, 30, 5, 250, tzinfo=UTC)
    assert make_run_id(cell, same_second) != a  # duas tentativas da mesma célula no mesmo segundo têm ids diferentes
    assert make_run_id(cell) != make_run_id(cell)  # e sem `now` também (relógio com resolução de microssegundo)
    free = Cell(task_id="x", modality="text", rep=0, provider="google", model_id="m",
                prompt_source=tasks and make_standard_source(tasks[0], "no_spec").model_copy(
                    update={"prompt_id": "free:coleta_1/p001/2"}))
    assert make_run_id(free).startswith("free-coleta_1-p001-2__text__google__r0__")


def test_short_workspace_id_is_short_and_stable():
    a = short_workspace_id("easy_pomodoro-no_spec__text__google__r0__20261009T143005")
    assert a == short_workspace_id("easy_pomodoro-no_spec__text__google__r0__20261009T143005")
    assert len(a) == 11 and a != short_workspace_id("outro")


def test_pilot_goes_to_a_separate_root(tmp_path):
    main, pilot = RunStore(tmp_path, "main"), RunStore(tmp_path, "pilot")
    assert main.root == tmp_path and pilot.root == tmp_path / "pilot"
    assert main.manifest_path != pilot.manifest_path


def test_save_load_and_last_attempt_wins(tmp_path, tasks):
    store = RunStore(tmp_path)
    cell = _cell(tasks)
    store.save(_record(cell, "run-1", status="api_error"))
    store.save(_record(cell, "run-2", status="done"))
    other = _cell(tasks, "with_spec")
    store.save(_record(other, "run-3", status="format_failure"))

    assert [e["run_id"] for e in store.manifest()] == ["run-1", "run-2", "run-3"]
    assert all("\\" not in e["record_path"] for e in store.manifest())
    records = {r.run_id: r for r in store.load_records()}
    assert set(records) == {"run-2", "run-3"}  # a tentativa api_error foi substituída
    assert (tmp_path / "runs" / "run-2" / "record.json").is_file()


def test_completed_keys_exclude_retryable_statuses(tmp_path, tasks):
    store = RunStore(tmp_path)
    for i, status in enumerate(["done", "api_error", "model_mismatch", "format_failure", "metric_error", "refusal"]):
        store.save(_record(_cell(tasks, rep=i), f"r{i}", status=status))
    done = store.completed_keys()
    assert len(done) == 4  # api_error e model_mismatch serão refeitas
    statuses = store.latest_status()
    assert {s for k, s in statuses.items() if k in done} == {"done", "format_failure", "metric_error", "refusal"}


def test_manifest_empty_when_no_runs(tmp_path):
    store = RunStore(tmp_path)
    assert store.manifest() == [] and store.completed_keys() == set() and store.load_records() == []


def test_artifact_resolves_relative_paths(tmp_path, tasks):
    store = RunStore(tmp_path)
    rec = _record(_cell(tasks), "run-9")
    rec.paths["screenshot"] = "screenshot.png"
    assert store.artifact(rec, "screenshot") == tmp_path / "runs" / "run-9" / "screenshot.png"


def test_flatten_record_prefixes_groups_and_drops_cases(tasks):
    rec = _record(
        _cell(tasks), "r", exec=ExecMetrics(format_ok=True, contract_ok=True, build_ok=True, executable=True),
        functional=FunctionalMetrics(accuracy_a=0.75, accuracy_b=0.5),
        technical=TechnicalMetrics(console_errors=["a", "b"], console_error_count=2,
                                   axe_violations={"critical": 1, "minor": 3}),
    )
    row = flatten_record(rec)
    assert row["exec_executable"] is True and row["fn_accuracy_a"] == 0.75
    assert row["tech_console_error_count"] == 2 and row["tech_axe_violations_critical"] == 1
    assert row["tech_console_errors_n"] == 2
    assert "fn_cases" not in row and "d2c_block_match" not in row  # grupo ausente => sem colunas
    assert row["status"] == "done" and row["provider"] == "google"


def test_aggregate_roundtrip(tmp_path, tasks):
    recs = [
        _record(_cell(tasks, rep=i), f"r{i}", functional=FunctionalMetrics(accuracy_a=i / 4))
        for i in range(3)
    ]
    df = records_to_dataframe(recs)
    paths = write_aggregate(df, tmp_path / "aggregate")
    back = pd.read_parquet(paths["runs"])
    assert list(back["fn_accuracy_a"]) == [0.0, 0.25, 0.5]
    long = pd.read_csv(paths["metrics_long"])
    assert {"run_id", "metric", "value"} <= set(long.columns)
    assert set(long.loc[long.metric == "fn_accuracy_a", "value"]) == {0.0, 0.25, 0.5}
    # valores ausentes não viram 0: não aparecem no formato longo
    assert long.loc[long.metric == "d2c_block_match"].empty
    assert json.loads(json.dumps(to_long(df).shape[0])) > 0


def test_smoke_runs_have_their_own_folder(tmp_path):
    smoke, pilot, main = RunStore(tmp_path, "smoke"), RunStore(tmp_path, "pilot"), RunStore(tmp_path, "main")
    assert smoke.root == tmp_path / "smoke" and pilot.root == tmp_path / "pilot" and main.root == tmp_path


def test_metrics_long_has_metrics_only(tmp_path):
    import pandas as pd

    from specui.storage import to_long

    df = pd.DataFrame([{
        "run_id": "r1", "task_id": "t", "prompt_kind": "no_spec", "modality": "text", "provider": "google",
        "model_id_requested": "m", "rep": 0, "status": "done",
        "fn_accuracy_a": 0.5, "emb_ves_dinov2": 0.9, "cq_apr": 0.1,
        "cq_counts_positioned_total": 12, "cq_counts_classes_total": 40,  # numeradores/denominadores: auditoria, não métrica
        "temperature": None, "seed": 7, "oracle_dirty": False,  # parâmetros e proveniência
    }])
    metrics = set(to_long(df)["metric"])
    assert metrics == {"fn_accuracy_a", "emb_ves_dinov2", "cq_apr"}
