"""Análise de itens: o que cada caso do oráculo realmente discrimina.

Por caso: nota média por condição (fonte × modalidade × modelo), `flag_floor` (0 % em todas as condições: ninguém passa;
suspeito de defeito do teste ou de caso fora do alcance), `flag_ceiling` (100 % em todas: o caso não discrimina),
`blocked_rate` (fração em que a pré-condição falhou) e discriminação (maior − menor média entre condições).
Só entram runs `done`; falhas de geração já estão na ITT.
"""

from collections.abc import Iterable

import pandas as pd

from specui.models import RunRecord

_POINTS = {"YES": 1.0, "PARTIAL": 0.5, "NO": 0.0}


def case_table(records: Iterable[RunRecord]) -> pd.DataFrame:
    """Uma linha por (run, caso executado): condição e pontuação."""
    rows = []
    for rec in records:
        if rec.status != "done" or rec.functional is None or rec.prompt_kind not in ("no_spec", "with_spec"):
            continue
        for c in rec.functional.cases:
            if c.outcome not in _POINTS:
                continue
            rows.append({
                "run_id": rec.run_id, "task_id": rec.task_id, "model": f"{rec.provider}:{rec.model_id_requested}",
                "spec": rec.prompt_kind, "modality": rec.modality, "case_id": c.case_id, "level": c.level,
                "score": _POINTS[c.outcome], "blocked": c.blocked, "outcome": c.outcome,
            })
    return pd.DataFrame(rows)


def item_analysis(records: Iterable[RunRecord]) -> pd.DataFrame:
    """Resumo por caso, com as flags de piso/teto e a discriminação por spec, modalidade e modelo."""
    cases = case_table(records)
    if cases.empty:
        return pd.DataFrame()
    cond = cases.groupby(["task_id", "case_id", "level", "model", "spec", "modality"])["score"].mean().reset_index()
    rows = []
    for (task_id, case_id, level), part in cond.groupby(["task_id", "case_id", "level"]):
        raw = cases[(cases["case_id"] == case_id) & (cases["task_id"] == task_id)]
        means = part["score"]
        row = {
            "task_id": task_id, "case_id": case_id, "level": level, "n": len(raw), "mean_score": raw["score"].mean(),
            "flag_floor": bool((means == 0).all()), "flag_ceiling": bool((means == 1).all()),
            "blocked_rate": raw["blocked"].mean(),
        }
        for factor in ("spec", "modality", "model"):
            by = part.groupby(factor)["score"].mean()
            row[f"discrimination_{factor}"] = float(by.max() - by.min()) if len(by) > 1 else None
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["task_id", "level", "case_id"]).reset_index(drop=True)


def accuracy_without_flagged(records: Iterable[RunRecord], items: pd.DataFrame) -> pd.DataFrame:
    """Nota de nível A com e sem os casos marcados (piso/teto), por spec: mostra se o efeito depende deles."""
    cases = case_table(records)
    if cases.empty or items.empty:
        return pd.DataFrame()
    flagged = set(items.loc[items["flag_floor"] | items["flag_ceiling"], "case_id"])
    level_a = cases[cases["level"] == "A"]
    per_run = level_a.groupby(["run_id", "spec"])["score"].mean().reset_index(name="with_all")
    kept = level_a[~level_a["case_id"].isin(flagged)].groupby("run_id")["score"].mean().rename("without_flagged")
    merged = per_run.merge(kept, on="run_id", how="left")
    return merged.groupby("spec")[["with_all", "without_flagged"]].mean().reset_index()
