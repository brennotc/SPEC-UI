"""Dados do painel (dashboard/app.py): funções puras, testáveis sem Streamlit. O painel só lê a execução PRINCIPAL."""

from pathlib import Path

import pandas as pd

from specui.models import RunRecord
from specui.storage import RunStore, records_to_dataframe


def load_main(results_dir: str | Path) -> tuple[list[RunRecord], pd.DataFrame]:
    """Records e quadro da execução principal (o piloto fica em results/pilot/ e nunca é lido aqui)."""
    records = RunStore(results_dir, "main").load_records()
    return records, records_to_dataframe(records)


def _rate(num: pd.Series, den: pd.Series) -> float | None:
    total = int(den.sum())
    return float(num[den].sum() / total) if total else None


def grid(df: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por modelo × tarefa × modalidade × fonte: n, taxas de formato/contrato/build/executabilidade e notas.

    Taxas (cada uma sobre o seu denominador): formato sobre todas; contrato sobre as de formato ok; build e
    executabilidade sobre as de contrato ok. `accuracy_a` e `ves` são condicionais (só quem executou).
    """
    if df.empty:
        return pd.DataFrame()
    work = df.copy()
    work["model"] = work["provider"] + ":" + work["model_id_requested"]
    flag = lambda col: work[col].fillna(False).astype(bool) if col in work else pd.Series(False, index=work.index)
    work["format_ok"], work["contract_ok"] = flag("exec_format_ok"), flag("exec_contract_ok")
    work["build_ok"], work["executable"] = flag("exec_build_ok"), flag("exec_executable")
    rows = []
    for key, part in work.groupby(["model", "task_id", "modality", "prompt_kind"]):
        fmt, ctr = part["format_ok"], part["contract_ok"]
        row = dict(zip(["model", "task_id", "modality", "prompt_kind"], key, strict=True))
        row |= {
            "n": len(part),
            "format_rate": float(fmt.mean()),
            "contract_rate": _rate(ctr, fmt),
            "build_rate": _rate(part["build_ok"], ctr),
            "executable_rate": _rate(part["executable"], ctr),
            "accuracy_a": part["fn_accuracy_a"].mean() if "fn_accuracy_a" in part else None,
            "ves": part["emb_ves_dinov2"].mean() if "emb_ves_dinov2" in part else None,
        }
        rows.append(row)
    return pd.DataFrame(rows)


def status_counts(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    return df.groupby(["provider", "model_id_requested", "status"]).size().reset_index(name="n")


def run_options(df: pd.DataFrame) -> list[str]:
    return df["run_id"].tolist() if not df.empty else []


def free_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Runs de prompts livres, com cobertura, densidade e o resultado (perfil só entra agregado no painel)."""
    if df.empty or "prompt_kind" not in df:
        return pd.DataFrame()
    free = df[df["prompt_kind"] == "free"]
    wanted = ["run_id", "prompt_id", "task_id", "modality", "status", "fn_accuracy_a", "fn_accuracy_a_restricted",
              "in_chars", "in_words", "in_requirement_coverage_total", "in_image_references"]
    return free[[c for c in wanted if c in free]]
