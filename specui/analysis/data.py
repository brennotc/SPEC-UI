"""Preparação do quadro de análise: conjuntos ITT e condicional, e as recusas (o `analyze` não agrega dado inválido).

ITT (padrão, métrica primária): toda geração tentada entra; `format_failure`, `contract_failure`, `nonexecutable`,
`refusal` e `truncated` valem 0. Condicional (secundária): só as executáveis, ao lado da taxa de executabilidade.
Ficam fora de QUALQUER conjunto: `api_error`, `metric_error`, `model_mismatch` (falhas de infraestrutura / modelo trocado).
"""

from typing import Literal

import pandas as pd

from specui.models import EXCLUDED_STATUSES, ITT_STATUSES

AnalysisSet = Literal["itt", "conditional"]
MAIN_SOURCES = ("no_spec", "with_spec")
SCORE = "accuracy_a"


class AnalysisRefused(RuntimeError):
    """Dados que não podem ser analisados como estão (a mensagem diz o que corrigir)."""


def _need(df: pd.DataFrame, columns: list[str]) -> None:
    missing = [c for c in columns if c not in df]
    if missing:
        raise AnalysisRefused(f"faltam colunas no quadro de runs: {missing}")


def prepare_frame(df: pd.DataFrame, run_kind: str = "main", allow_mixed_oracle: bool = False) -> pd.DataFrame:
    """Valida o quadro de runs e acrescenta `model`, `spec`, `accuracy_itt` e `accuracy_cond`.

    Recusa: runs `pilot` misturados, `metric_error` em `main` (resolver com `specui evaluate`), mais de uma versão
    do oráculo ou do navegador (Playwright/Chromium), `done` sem nota funcional.
    """
    _need(df, ["run_id", "status", "prompt_kind", "task_id", "modality", "provider", "model_id_requested"])
    df = df.copy()
    if "run_kind" in df and (df["run_kind"] != run_kind).any():
        raise AnalysisRefused(f"o quadro mistura run_kind diferente de '{run_kind}' (o piloto fica fora da análise)")
    if (df["provider"] == "mock").any():
        raise AnalysisRefused("o quadro contém runs do gerador simulado (mock): dado de teste nunca entra na análise")
    broken = df.loc[df["status"] == "metric_error", "run_id"].tolist()
    if broken:
        raise AnalysisRefused(
            f"{len(broken)} run(s) com metric_error: rode `specui evaluate --run-id <id>` antes de analisar. "
            f"Runs: {', '.join(broken[:10])}{' ...' if len(broken) > 10 else ''}"
        )
    unknown = sorted(set(df["status"]) - ITT_STATUSES - EXCLUDED_STATUSES)
    if unknown:
        raise AnalysisRefused(f"status desconhecidos: {unknown}")

    if not allow_mixed_oracle:
        for column in ("oracle_content_sha256", "oracle_suite_tag"):
            if column in df and df[column].dropna().nunique() > 1:
                raise AnalysisRefused(
                    f"runs de versões diferentes do oráculo ({column}): {sorted(df[column].dropna().unique())}. "
                    "Mudar o oráculo exige reexecutar as células."
                )
    # O navegador também é instrumento: todas as métricas visuais e o oráculo dependem do render. Reavaliar (`specui evaluate`)
    # numa máquina/Chromium diferente misturaria navegadores em silêncio.
    for column in ("playwright_version", "browser_version"):
        if column in df and df[column].dropna().nunique() > 1:
            raise AnalysisRefused(
                f"runs com navegadores diferentes ({column}): {sorted(df[column].dropna().unique())}. "
                "Reavalie todas as células na mesma máquina e versão do Playwright/Chromium (requirements.lock)."
            )

    df = df[~df["status"].isin(EXCLUDED_STATUSES)].copy()  # infraestrutura / modelo trocado: fora de tudo
    df["model"] = df["provider"] + ":" + df["model_id_requested"]
    df["spec"] = df["prompt_kind"]

    score = df["fn_accuracy_a"] if "fn_accuracy_a" in df else pd.Series(float("nan"), index=df.index)
    ran = df["status"] == "done"
    if score[ran].isna().any():
        ids = df.loc[ran & score.isna(), "run_id"].tolist()
        raise AnalysisRefused(f"{len(ids)} run(s) 'done' sem nota funcional (oráculo não executou?): {ids[:10]}")
    df["accuracy_itt"] = score.where(ran, 0.0)  # falha de geração/execução vale 0
    executable = df["exec_executable"].fillna(False).astype(bool) if "exec_executable" in df else ran
    df["accuracy_cond"] = score.where(ran & executable)
    return df


def spec_frame(df: pd.DataFrame, value: str) -> pd.DataFrame:
    """Só as fontes no_spec/with_spec e a coluna de nota pedida, sem ausentes (conjunto condicional descarta NaN)."""
    sub = df[df["spec"].isin(MAIN_SOURCES)]
    return sub.dropna(subset=[value])


def executability(df: pd.DataFrame) -> pd.DataFrame:
    """Taxa de executabilidade por modelo × tarefa × modalidade × fonte (acompanha SEMPRE a análise condicional)."""
    sub = df[df["spec"].isin(MAIN_SOURCES)].copy()
    sub["executable"] = (sub["accuracy_cond"].notna()).astype(float)
    return (
        sub.groupby(["model", "task_id", "modality", "spec"])
        .agg(n=("run_id", "size"), executable_rate=("executable", "mean"))
        .reset_index()
    )
