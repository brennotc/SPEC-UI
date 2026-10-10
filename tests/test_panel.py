"""Dados do painel e fumaça do dashboard (sem navegador)."""

import pandas as pd
import pytest

from specui.analysis.panel import free_rows, grid, status_counts


def frame():
    rows = []
    for i, (fmt, ctr, build, exe, acc) in enumerate([
        (True, True, True, True, 0.8), (True, True, False, False, None), (True, False, None, None, None), (False, None, None, None, None),
    ]):
        rows.append({"run_id": f"r{i}", "provider": "google", "model_id_requested": "g", "task_id": "easy_pomodoro", "modality": "text",
                     "prompt_kind": "no_spec", "exec_format_ok": fmt, "exec_contract_ok": ctr, "exec_build_ok": build,
                     "exec_executable": exe, "fn_accuracy_a": acc, "emb_ves_dinov2": 0.9 if acc else None})
    return pd.DataFrame(rows)


def test_grid_rates_use_their_own_denominators():
    row = grid(frame()).iloc[0]
    assert row["n"] == 4 and row["format_rate"] == 0.75  # formato sobre todas
    assert row["contract_rate"] == pytest.approx(2 / 3)  # contrato sobre as de formato ok
    assert row["build_rate"] == 0.5 and row["executable_rate"] == 0.5  # sobre as de contrato ok
    assert row["accuracy_a"] == 0.8 and row["ves"] == 0.9  # condicionais: quem não executou não entra


def test_grid_and_helpers_handle_empty_frames():
    assert grid(pd.DataFrame()).empty and status_counts(pd.DataFrame()).empty and free_rows(pd.DataFrame()).empty


def test_free_rows_only_free_prompts():
    df = frame()
    df.loc[0, "prompt_kind"] = "free"
    df["prompt_id"], df["status"], df["in_words"] = "free:c/p001/1", "done", 10
    out = free_rows(df)
    assert list(out["run_id"]) == ["r0"] and "in_words" in out


def test_dashboard_runs_on_an_empty_results_dir(repo_root, tmp_path):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(repo_root / "dashboard" / "app.py"), default_timeout=60)
    at.run()
    assert not at.exception
    at.sidebar.text_input[0].set_value(str(tmp_path / "vazio")).run()
    assert not at.exception and any("Nenhuma execução principal" in i.value for i in at.info)


def test_dashboard_renders_with_stored_runs(repo_root, tmp_path):
    from streamlit.testing.v1 import AppTest

    from specui.storage import RunStore
    from tests.test_analysis import _stored_runs

    results = tmp_path / "results"
    _stored_runs(RunStore(results, "main"))
    at = AppTest.from_file(str(repo_root / "dashboard" / "app.py"), default_timeout=120)
    at.run()
    at.sidebar.text_input[0].set_value(str(results)).run()
    assert not at.exception, [e.value for e in at.exception]
    assert len(at.tabs) == 6
