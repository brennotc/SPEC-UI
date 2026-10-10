"""Prompts livres de participantes: o grau de especificação como variável contínua.

Regressão da nota sobre a cobertura de requisitos e a densidade de restrições do TEXTO do participante (controlando tarefa,
modalidade e modelo), com erros agrupados por participante (vários prompts do mesmo autor não são independentes). ITT por
padrão. `no_spec` e `with_spec` entram como pontos de referência da dispersão. Recusa misturar hashes de `mention_patterns`.
"""

import numpy as np
import pandas as pd

from specui.analysis.data import AnalysisRefused


def participant_of(prompt_id: str) -> str | None:
    """`free:<coleta>/<participante>/<n>` -> `<coleta>/<participante>`."""
    if not prompt_id.startswith("free:"):
        return None
    parts = prompt_id.removeprefix("free:").split("/")
    return "/".join(parts[:2]) if len(parts) >= 2 else parts[0]


def free_frame(df: pd.DataFrame, value: str = "accuracy_itt", restricted: bool = True) -> pd.DataFrame:
    """Quadro dos runs livres com cobertura, densidade e participante; recusa `mention_patterns` de hashes diferentes."""
    free = df[df["spec"] == "free"].copy() if "spec" in df else df.iloc[0:0].copy()
    if free.empty:
        return free
    if "mention_patterns_sha256" in free and free["mention_patterns_sha256"].dropna().nunique() > 1:
        raise AnalysisRefused("runs livres com `mention_patterns` diferentes: os padrões foram congelados antes da coleta")
    free["participant"] = free["prompt_id"].map(participant_of)
    free["coverage"] = free.get("in_requirement_coverage_total")
    density_cols = [c for c in free.columns if c.startswith("in_constraint_density_")]
    free["constraint_density"] = free[density_cols].sum(axis=1) if density_cols else 0
    free["constraint_density_per_100_words"] = 100 * free["constraint_density"] / free["in_words"].replace(0, np.nan)
    score = "fn_accuracy_a_restricted" if restricted and "fn_accuracy_a_restricted" in free else "fn_accuracy_a"
    free["score_free"] = free[score].where(free["status"] == "done", 0.0) if value == "accuracy_itt" else free[score]
    stack_cols = [c for c in free.columns if c.startswith("in_stack_requests_") and not c.endswith("outros")]
    free["stack_any"] = free[stack_cols].fillna(False).astype(bool).any(axis=1) if stack_cols else False
    return free


def free_regression(free: pd.DataFrame) -> dict:
    """OLS: nota ~ cobertura + densidade + tarefa + modalidade + modelo, erros agrupados por participante."""
    import statsmodels.formula.api as smf

    data = free.dropna(subset=["score_free", "coverage", "constraint_density_per_100_words"])
    if len(data) < 8 or data["participant"].nunique() < 3:
        return {"error": f"poucos dados para a regressão ({len(data)} runs, {data['participant'].nunique()} participantes)"}
    terms = "coverage + constraint_density_per_100_words + C(task_id) + C(modality)"
    if data["model"].nunique() > 1:
        terms += " + C(model)"
    try:
        fit = smf.ols(f"score_free ~ {terms}", data=data).fit(cov_type="cluster", cov_kwds={"groups": pd.factorize(data["participant"])[0]})
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}
    table = pd.DataFrame({"coef": fit.params, "se": fit.bse, "p": fit.pvalues})
    return {"formula": f"score_free ~ {terms}", "n": int(fit.nobs), "clusters": int(data["participant"].nunique()),
            "coefficients": table.reset_index(names="term").to_dict("records")}


def contract_failure_by_source(df: pd.DataFrame) -> pd.DataFrame:
    """Taxa de `contract_failure` por fonte; nos livres, cruzada com pedidos de outra stack (`stack_any`)."""
    sub = df.copy()
    sub["contract_failure"] = (sub["status"] == "contract_failure").astype(float)
    stack_cols = [c for c in sub.columns if c.startswith("in_stack_requests_") and not c.endswith("outros")]
    sub["stack_any"] = sub[stack_cols].fillna(False).astype(bool).any(axis=1) if stack_cols else False
    out = sub.groupby(["spec", "stack_any"]).agg(n=("run_id", "size"), contract_failure_rate=("contract_failure", "mean")).reset_index()
    return out
