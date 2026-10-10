"""Análise estatística com dados sintéticos de efeito conhecido."""

import numpy as np
import pandas as pd
import pytest

from specui.analysis import (
    AnalysisRefused,
    consistency,
    main_contrast,
    ols_robustness,
    prepare_frame,
)
from specui.analysis.contrasts import forest_figure, stratum_table
from specui.analysis.data import executability, spec_frame
from specui.analysis.free import (
    contract_failure_by_source,
    free_frame,
    free_regression,
    participant_of,
)
from specui.analysis.items import accuracy_without_flagged, item_analysis
from specui.analysis.report import analyze_frame, run_analysis
from specui.config import load_config
from specui.models import CaseOutcome, FunctionalMetrics, RunRecord
from specui.storage import RunStore, records_to_dataframe

TASKS = ["easy_pomodoro", "medium_tarefas", "hard_kanban"]
MODALITIES = ["text", "multimodal"]
FAST = {"n_boot": 400, "n_perm": 400}


def synthetic(effects: dict[str, float], reps: int = 6, noise: float = 0.05, seed: int = 1, failures: dict | None = None) -> pd.DataFrame:
    """Um quadro de runs como `records_to_dataframe`: nota = base + efeito·(with_spec) + ruído."""
    rng = np.random.default_rng(seed)
    rows = []
    for model, effect in effects.items():
        provider, model_id = model.split(":")
        for task in TASKS:
            for modality in MODALITIES:
                for spec in ("no_spec", "with_spec"):
                    for rep in range(reps):
                        score = float(np.clip(0.4 + effect * (spec == "with_spec") + rng.normal(0, noise), 0, 1))
                        status = "done"
                        if failures and rng.random() < failures.get(spec, 0.0):
                            status = "nonexecutable"
                        rows.append({
                            "run_id": f"{model}-{task}-{modality}-{spec}-{rep}", "run_kind": "main", "status": status,
                            "prompt_kind": spec, "task_id": task, "modality": modality, "provider": provider,
                            "model_id_requested": model_id, "rep": rep,
                            "fn_accuracy_a": score if status == "done" else None,
                            "exec_executable": status == "done", "oracle_content_sha256": "abc", "oracle_suite_tag": "oracle-v1",
                        })
    return pd.DataFrame(rows)


def itt(df):
    return spec_frame(prepare_frame(df), "accuracy_itt")


def test_known_effect_is_recovered_with_ci_and_small_p():
    results = main_contrast(itt(synthetic({"google:g": 0.30, "google:h": 0.0})), **FAST)
    g, c = results["google:g"], results["google:h"]
    assert g.effect == pytest.approx(0.30, abs=0.05) and g.ci_above_zero and g.p_perm < 0.01
    assert abs(c.effect) < 0.05 and c.ci_low < 0 < c.ci_high and c.p_perm > 0.05
    assert g.n_strata == 6 and g.n_runs == 72


def test_ci_covers_the_true_effect_most_of_the_time():
    covered = 0
    for seed in range(1, 41):
        r = main_contrast(itt(synthetic({"google:g": 0.30}, seed=seed)), n_boot=300, n_perm=50)["google:g"]
        covered += r.ci_low <= 0.30 <= r.ci_high
    assert covered / 40 >= 0.85  # IC de 95 %: tolerância para a variação da amostra de 40 réplicas


def test_permutation_p_is_not_small_without_an_effect():
    ps = [main_contrast(itt(synthetic({"google:g": 0.0}, seed=s)), **FAST)["google:g"].p_perm for s in range(1, 9)]
    assert np.mean(ps) > 0.25 and sum(p < 0.05 for p in ps) <= 2  # ≈ uniforme sob a nula


def test_itt_counts_failures_as_zero_and_differs_from_conditional():
    df = synthetic({"google:g": 0.0}, failures={"with_spec": 0.5}, seed=3)
    frame = prepare_frame(df)
    assert (frame.loc[frame["status"] == "nonexecutable", "accuracy_itt"] == 0).all()
    assert frame.loc[frame["status"] == "nonexecutable", "accuracy_cond"].isna().all()
    res_itt = main_contrast(spec_frame(frame, "accuracy_itt"), **FAST)["google:g"]
    res_cond = main_contrast(spec_frame(frame, "accuracy_cond"), **FAST)["google:g"]
    assert res_itt.effect < -0.1  # a spec "perde" metade das gerações: o ITT mostra, o condicional esconde
    assert abs(res_cond.effect) < 0.05
    rate = executability(frame)
    assert rate.loc[rate["spec"] == "with_spec", "executable_rate"].mean() < rate.loc[rate["spec"] == "no_spec", "executable_rate"].mean()


@pytest.mark.parametrize("status", ["api_error", "model_mismatch"])
def test_infrastructure_failures_are_in_no_set(status):
    df = synthetic({"google:g": 0.2})
    df.loc[0:4, "status"] = status
    df.loc[0:4, "fn_accuracy_a"] = None
    frame = prepare_frame(df)
    assert len(frame) == len(df) - 5 and status not in set(frame["status"])


def test_metric_error_in_main_refuses_and_lists_the_runs():
    df = synthetic({"google:g": 0.2})
    df.loc[3, "status"] = "metric_error"
    with pytest.raises(AnalysisRefused, match="metric_error") as err:
        prepare_frame(df)
    assert df.loc[3, "run_id"] in str(err.value) and "specui evaluate" in str(err.value)


def test_mixed_oracle_versions_and_pilot_runs_are_refused():
    df = synthetic({"google:g": 0.2})
    df.loc[0, "oracle_content_sha256"] = "outro"
    with pytest.raises(AnalysisRefused, match="versões diferentes do oráculo"):
        prepare_frame(df)
    pilot = synthetic({"google:g": 0.2})
    pilot.loc[0, "run_kind"] = "pilot"
    with pytest.raises(AnalysisRefused, match="piloto"):
        prepare_frame(pilot)
    missing = synthetic({"google:g": 0.2})
    missing.loc[0, "fn_accuracy_a"] = None  # 'done' sem nota: o oráculo não rodou
    with pytest.raises(AnalysisRefused, match="sem nota funcional"):
        prepare_frame(missing)


def test_contrast_needs_the_model_factor():
    with pytest.raises(ValueError, match="fator modelo"):
        main_contrast(synthetic({"google:g": 0.1}).assign(spec="x").drop(columns=["provider"]))


def test_consistency_signs_differences_and_tost():
    results = main_contrast(itt(synthetic({"google:g": 0.30, "google:h": 0.28, "mock:m": 0.0})), **FAST)
    cons = consistency(results, equivalence_margin=None)
    assert len(cons["differences"]) == 3  # k = 3: todos os pares
    assert cons["tost"]["ran"] is False and "equivalence_margin" in cons["tost"]["reason"]
    assert cons["n_strata"] == 6
    with_margin = consistency(results, equivalence_margin=0.1)
    by_pair = {(d["a"], d["b"]): d for d in with_margin["differences"]}
    assert with_margin["tost"]["ran"] is True
    assert by_pair[("google:g", "google:h")]["equivalent"] is True  # 0,30 vs 0,28 dentro de ±0,10
    assert by_pair[("google:h", "mock:m")]["equivalent"] is False
    same = consistency(main_contrast(itt(synthetic({"google:g": 0.3, "google:h": 0.3}, noise=0.01)), **FAST))
    assert same["n_strata_same_sign"] == 6


def test_stratum_table_ols_and_forest():
    results = main_contrast(itt(synthetic({"google:g": 0.3, "google:h": 0.1})), **FAST)
    table = stratum_table(results)
    assert len(table) == 12 and {"model", "task_id", "modality", "delta"} <= set(table.columns)
    ols = ols_robustness(itt(synthetic({"google:g": 0.3, "google:h": 0.1})))
    terms = {c["term"]: c for c in ols["coefficients"]}
    assert "C(spec)[T.with_spec]" in terms and "C(spec)[T.with_spec]:C(model)[T.google:h]" in terms
    fig = forest_figure(results, consistency(results)["differences"])
    assert len(fig.data) == 1 and len(fig.data[0].y) == 3  # 2 modelos + 1 diferença


# ----------------------------------------------------------------------------- itens e livres


def _record(i, spec="no_spec", status="done", cases=(), model="g", prompt_id=None, **kw) -> RunRecord:
    outcomes = [CaseOutcome(case_id=c, level="A", outcome=o, requirements=[], blocked=(o == "NO" and b)) for c, o, b in cases]
    rec = RunRecord(
        run_id=f"r{i}", run_kind="main", cell_key=f"k{i}", task_id="easy_pomodoro", difficulty="easy", prompt_kind=spec,
        prompt_id=prompt_id or f"easy_pomodoro/{spec}", modality="text", rep=i, created_at="2026-10-09T00:00:00+00:00",
        provider="google", model_id_requested=model, prompt_sha256="p", envelope_sha256="e", envelope_version="2",
        status=status, functional=FunctionalMetrics(accuracy_a=0.5, cases=outcomes), **kw,
    )
    rec.exec.executable = status == "done"
    return rec


def test_item_flags_floor_ceiling_and_discrimination():
    records = []
    for i in range(6):
        spec = "with_spec" if i % 2 else "no_spec"
        records.append(_record(i, spec, cases=[("C-ceiling", "YES", False), ("C-floor", "NO", True),
                                              ("C-disc", "YES" if spec == "with_spec" else "NO", False)]))
    items = item_analysis(records).set_index("case_id")
    assert items.loc["C-ceiling", "flag_ceiling"] and not items.loc["C-ceiling", "flag_floor"]
    assert items.loc["C-floor", "flag_floor"] and items.loc["C-floor", "blocked_rate"] == 1.0
    assert not items.loc["C-disc", "flag_floor"] and not items.loc["C-disc", "flag_ceiling"]
    assert items.loc["C-disc", "discrimination_spec"] == 1.0
    summary = accuracy_without_flagged(records, items.reset_index()).set_index("spec")
    assert summary.loc["with_spec", "without_flagged"] == 1.0 and summary.loc["no_spec", "without_flagged"] == 0.0


def test_free_prompts_participants_regression_and_hash_guard():
    assert participant_of("free:c1/p007/2") == "c1/p007" and participant_of("easy_pomodoro/no_spec") is None
    rng = np.random.default_rng(0)
    rows = []
    for i in range(60):
        cov = float(rng.random())
        rows.append({
            "run_id": f"f{i}", "run_kind": "main", "status": "done", "prompt_kind": "free", "prompt_id": f"free:c1/p{i % 12:03d}/{i}",
            "task_id": TASKS[i % 3], "modality": MODALITIES[i % 2], "provider": "google", "model_id_requested": "g",
            "fn_accuracy_a": 0.2 + 0.6 * cov + rng.normal(0, 0.03), "fn_accuracy_a_restricted": 0.2 + 0.6 * cov, "exec_executable": True,
            "in_requirement_coverage_total": cov, "in_constraint_density_hex": i % 5, "in_words": 40 + i % 7,
            "mention_patterns_sha256": "m1", "oracle_content_sha256": "o", "oracle_suite_tag": "oracle-v1",
        })
    frame = prepare_frame(pd.DataFrame(rows))
    free = free_frame(frame)
    out = free_regression(free)
    coef = {c["term"]: c for c in out["coefficients"]}
    assert out["clusters"] == 12 and coef["coverage"]["coef"] == pytest.approx(0.6, abs=0.1) and coef["coverage"]["p"] < 0.01
    frame.loc[0, "mention_patterns_sha256"] = "m2"
    with pytest.raises(AnalysisRefused, match="mention_patterns"):
        free_frame(frame)
    assert "error" in free_regression(free.head(3))


def test_contract_failure_rate_by_source_and_stack():
    df = synthetic({"google:g": 0.0}, reps=2)
    df["status"] = "done"
    df.loc[df.index[:4], "status"] = "contract_failure"
    df["in_stack_requests_react"] = False
    frame = prepare_frame(df.assign(fn_accuracy_a=df["fn_accuracy_a"].fillna(0.5)))
    table = contract_failure_by_source(frame)
    assert {"spec", "stack_any", "n", "contract_failure_rate"} <= set(table.columns)
    assert table["contract_failure_rate"].max() > 0


# ----------------------------------------------------------------------------- ponta a ponta


def _stored_runs(store: RunStore) -> None:
    rng = np.random.default_rng(5)
    i = 0
    for model in ("g", "c"):
        for task in TASKS:
            for modality in MODALITIES:
                for spec in ("no_spec", "with_spec"):
                    for rep in range(3):
                        score = float(np.clip(0.4 + 0.3 * (spec == "with_spec") + rng.normal(0, 0.05), 0, 1))
                        rec = _record(i, spec, model=model, cases=[("X-A-01", "YES" if score > 0.5 else "NO", False)])
                        rec.task_id, rec.modality, rec.rep = task, modality, rep
                        rec.cell_key = f"{model}-{task}-{modality}-{spec}-{rep}"
                        rec.functional.accuracy_a = score
                        rec.oracle_content_sha256, rec.oracle_suite_tag = "abc", "oracle-v1"
                        rec.paths["run_dir"] = f"runs/r{i}"
                        store.save(rec)
                        i += 1


def test_run_analysis_writes_report_and_refuses_a_changed_margin(repo_root, tmp_path):
    cfg = load_config(repo_root / "configs" / "default.yaml",
                      overrides={"results_dir": str(tmp_path / "results"), "analysis": {"n_boot": 300, "n_perm": 300}})
    store = RunStore(cfg.path("results_dir"), "main")
    _stored_runs(store)
    store.freeze_meta(None, "sha")
    paths = run_analysis(cfg)
    report = paths["report"].read_text(encoding="utf-8")
    assert report.index("Métrica primária") < report.index("condicional") and "Consistência entre modelos" in report
    assert "nos modelos testados" in report and "TOST" in report
    assert paths["analysis"].is_file() and paths["forest"].is_file() and paths["runs"].is_file()

    changed = cfg.model_copy(update={"analysis": cfg.analysis.model_copy(update={"equivalence_margin": 0.1})})
    with pytest.raises(AnalysisRefused, match="equivalence_margin"):
        run_analysis(changed)
    with pytest.raises(ValueError, match="mudou depois do congelamento"):
        store.freeze_meta(0.2, "sha")


def test_analyze_frame_without_main_pairs_does_not_crash(repo_root, tmp_path):
    cfg = load_config(repo_root / "configs" / "default.yaml", overrides={"results_dir": str(tmp_path), "analysis": {"n_boot": 100, "n_perm": 100}})
    df = synthetic({"google:g": 0.2}, reps=2)
    out = analyze_frame(df, cfg)
    assert out["models"] == ["google:g"] and out["consistency"]["differences"] == []
    assert records_to_dataframe([]).empty


def test_freeze_meta_warns_when_the_config_hash_changes_but_only_refuses_a_new_margin(tmp_path, caplog):
    store = RunStore(tmp_path, "main")
    store.freeze_meta(None, "hash-a" * 8)
    with caplog.at_level("WARNING", logger="specui.storage"):
        assert store.freeze_meta(None, "hash-b" * 8)["config_sha256"] == "hash-a" * 8
    assert "configuração mudou" in caplog.text
    with pytest.raises(ValueError, match="mudou depois do congelamento"):
        store.freeze_meta(0.1, "hash-a" * 8)
