"""Contraste principal e consistência entre modelos.

Efeito da spec por modelo = média, sobre os estratos tarefa × modalidade, de Δ = média(with_spec) − média(no_spec).
As gerações são independentes, então NÃO há pareamento por índice de repetição: o IC vem de bootstrap estratificado
(reamostra com reposição dentro de cada estrato × fonte) e o p, de permutação estratificada (embaralha os rótulos
spec/no_spec dentro de cada estrato). Consistência entre modelos: sinal por estrato, diferença entre efeitos (IC pelo
mesmo bootstrap) e, se houver margem, equivalência (IC de 90 % dentro de ±margem). Nunca se conclui igualdade a partir de
interação não significativa.
"""

from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

import numpy as np
import pandas as pd

STRATA = ["task_id", "modality"]


@dataclass
class StratumEffect:
    task_id: str
    modality: str
    delta: float
    n_no_spec: int
    n_with_spec: int
    ci_low: float | None = None
    ci_high: float | None = None


@dataclass
class EffectResult:
    model: str
    effect: float
    ci_low: float
    ci_high: float
    p_perm: float
    n_strata: int
    n_runs: int
    strata: list[StratumEffect] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # estratos sem uma das fontes
    boot: np.ndarray = field(default_factory=lambda: np.empty(0), repr=False)

    @property
    def ci_above_zero(self) -> bool:
        return self.ci_low > 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "model": self.model, "effect": self.effect, "ci_low": self.ci_low, "ci_high": self.ci_high,
            "p_perm": self.p_perm, "n_strata": self.n_strata, "n_runs": self.n_runs,
            "ci_above_zero": self.ci_above_zero, "skipped": self.skipped,
            "strata": [vars(s) for s in self.strata],
        }


def _arms(df: pd.DataFrame, value: str) -> tuple[dict[tuple[str, str], tuple[np.ndarray, np.ndarray]], list[str]]:
    arms, skipped = {}, []
    for key, part in df.groupby(STRATA):
        no = part.loc[part["spec"] == "no_spec", value].to_numpy(float)
        yes = part.loc[part["spec"] == "with_spec", value].to_numpy(float)
        if len(no) and len(yes):
            arms[key] = (no, yes)
        else:
            skipped.append("/".join(key))
    return arms, skipped


def _boot_means(rng: np.random.Generator, values: np.ndarray, n_boot: int) -> np.ndarray:
    return values[rng.integers(0, len(values), size=(n_boot, len(values)))].mean(axis=1)


def _perm_stat(rng: np.random.Generator, arms: dict, n_perm: int) -> np.ndarray:
    deltas = []
    for no, yes in arms.values():
        pooled = np.concatenate([no, yes])
        order = rng.random((n_perm, len(pooled))).argsort(axis=1)
        shuffled = pooled[order]
        deltas.append(shuffled[:, len(no):].mean(axis=1) - shuffled[:, : len(no)].mean(axis=1))
    return np.mean(deltas, axis=0)


def _contrast_for_model(
    model: str, df: pd.DataFrame, value: str, n_boot: int, n_perm: int, alpha: float, seed: int
) -> EffectResult:
    arms, skipped = _arms(df, value)
    if not arms:
        raise ValueError(f"{model}: nenhum estrato tem as duas fontes (no_spec e with_spec)")
    rng = np.random.default_rng(seed)

    observed = np.mean([yes.mean() - no.mean() for no, yes in arms.values()])
    strata, boot_deltas = [], []
    for (task_id, modality), (no, yes) in arms.items():
        delta_boot = _boot_means(rng, yes, n_boot) - _boot_means(rng, no, n_boot)
        boot_deltas.append(delta_boot)
        lo, hi = np.percentile(delta_boot, [100 * alpha / 2, 100 * (1 - alpha / 2)])
        strata.append(StratumEffect(task_id, modality, float(yes.mean() - no.mean()), len(no), len(yes), float(lo), float(hi)))
    boot = np.mean(boot_deltas, axis=0)
    lo, hi = np.percentile(boot, [100 * alpha / 2, 100 * (1 - alpha / 2)])

    perm = _perm_stat(rng, arms, n_perm)
    p = (1 + int(np.sum(np.abs(perm) >= abs(observed) - 1e-12))) / (1 + n_perm)
    n_runs = int(sum(len(no) + len(yes) for no, yes in arms.values()))
    return EffectResult(model, float(observed), float(lo), float(hi), float(p), len(arms), n_runs, strata, skipped, boot)


def main_contrast(
    df: pd.DataFrame, value: str = "accuracy_itt", n_boot: int = 10_000, n_perm: int = 10_000,
    alpha: float = 0.05, seed: int = 20260101,
) -> dict[str, EffectResult]:
    """Efeito médio da spec por modelo (o único contraste principal). `df` vem de `prepare_frame` + `spec_frame`."""
    if "model" not in df:
        raise ValueError("o quadro precisa da coluna 'model' (a análise nunca agrega modelos diferentes sem o fator modelo)")
    results = {}
    for i, (model, part) in enumerate(df.groupby("model")):
        results[str(model)] = _contrast_for_model(str(model), part, value, n_boot, n_perm, alpha, seed + i)
    return results


def stratum_table(results: dict[str, EffectResult]) -> pd.DataFrame:
    """Δ por estrato × modelo (secundário)."""
    rows = [
        {"model": r.model, "task_id": s.task_id, "modality": s.modality, "delta": s.delta,
         "ci_low": s.ci_low, "ci_high": s.ci_high, "n_no_spec": s.n_no_spec, "n_with_spec": s.n_with_spec}
        for r in results.values() for s in r.strata
    ]
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------- consistência entre modelos


def consistency(
    results: dict[str, EffectResult], alpha: float = 0.05, equivalence_margin: float | None = None
) -> dict[str, Any]:
    """Sinal do Δ por estrato em cada modelo, diferença entre efeitos (todos os pares) com IC e, opcionalmente, TOST."""
    models = list(results)
    table = stratum_table(results)
    sign_rows, agreeing = [], 0
    if len(models) > 1 and not table.empty:
        wide = table.pivot_table(index=["task_id", "modality"], columns="model", values="delta")
        for key, row in wide.dropna().iterrows():
            signs = np.sign(row.to_numpy())
            same = bool(len(set(signs)) == 1 and signs[0] != 0)
            agreeing += same
            sign_rows.append({"task_id": key[0], "modality": key[1], **{m: float(row[m]) for m in models}, "same_sign": same})

    differences = []
    for a, b in combinations(models, 2):
        n = min(len(results[a].boot), len(results[b].boot))
        diff = results[a].boot[:n] - results[b].boot[:n]
        lo, hi = np.percentile(diff, [100 * alpha / 2, 100 * (1 - alpha / 2)])
        entry: dict[str, Any] = {"a": a, "b": b, "difference": results[a].effect - results[b].effect,
                                 "ci_low": float(lo), "ci_high": float(hi)}
        if equivalence_margin is not None:
            lo90, hi90 = np.percentile(diff, [100 * alpha, 100 * (1 - alpha)])  # TOST: IC de (1 − 2α) dentro da margem
            entry |= {"tost_ci_low": float(lo90), "tost_ci_high": float(hi90),
                      "equivalent": bool(-equivalence_margin < lo90 and hi90 < equivalence_margin)}
        differences.append(entry)

    tost = (
        {"margin": equivalence_margin, "ran": True}
        if equivalence_margin is not None and differences
        else {"margin": None, "ran": False,
              "reason": "analysis.equivalence_margin é null (definir ANTES da execução principal)" if equivalence_margin is None
              else "menos de dois modelos"}
    )
    return {"signs": sign_rows, "n_strata_same_sign": agreeing, "n_strata": len(sign_rows),
            "differences": differences, "tost": tost}


def ols_robustness(df: pd.DataFrame, value: str = "accuracy_itt") -> dict[str, Any]:
    """OLS com erros HC3: nota ~ spec*modalidade + tarefa + modelo + spec:modelo (checagem de robustez; secundária)."""
    import statsmodels.formula.api as smf

    sub = df[df["spec"].isin(["no_spec", "with_spec"])].copy()
    sub["score"] = sub[value]
    terms = "C(spec) * C(modality) + C(task_id)"
    if sub["model"].nunique() > 1:
        terms += " + C(model) + C(spec):C(model)"
    try:
        fit = smf.ols(f"score ~ {terms}", data=sub).fit(cov_type="HC3")
    except Exception as exc:  # noqa: BLE001 - matriz singular, estrato vazio...
        return {"error": f"{type(exc).__name__}: {exc}"}
    table = pd.DataFrame({"coef": fit.params, "se": fit.bse, "p": fit.pvalues})
    return {"formula": f"score ~ {terms}", "n": int(fit.nobs), "coefficients": table.reset_index(names="term").to_dict("records")}


def forest_figure(results: dict[str, EffectResult], differences: list[dict[str, Any]] | None = None):
    """Forest: efeito da spec por modelo (e diferenças entre modelos) com IC de 95 %."""
    import plotly.graph_objects as go

    labels = [m for m in results] + [f"{d['a']} − {d['b']}" for d in (differences or [])]
    centers = [r.effect for r in results.values()] + [d["difference"] for d in (differences or [])]
    lows = [r.ci_low for r in results.values()] + [d["ci_low"] for d in (differences or [])]
    highs = [r.ci_high for r in results.values()] + [d["ci_high"] for d in (differences or [])]
    fig = go.Figure(go.Scatter(
        x=centers, y=labels, mode="markers",
        error_x={"type": "data", "symmetric": False, "array": [h - c for h, c in zip(highs, centers, strict=True)],
                 "arrayminus": [c - lo for c, lo in zip(centers, lows, strict=True)]},
    ))
    fig.add_vline(x=0, line_dash="dash")
    fig.update_layout(title="Efeito da spec (accuracy_a, ITT) por modelo, IC 95 %", xaxis_title="with_spec − no_spec", height=120 + 60 * len(labels))
    return fig
