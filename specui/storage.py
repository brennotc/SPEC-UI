"""Armazenamento dos resultados em results/ (INTEIRAMENTE fora do git).

    results/runs/<run_id>/record.json + artefatos     (execuções main)
    results/manifest.jsonl                             (uma linha por tentativa; a última vence)
    results/pilot/...                                  (piloto: mesma estrutura, fora da análise)
    results/aggregate/runs.parquet, metrics_long.csv   (gerados por `specui analyze`)
"""

import hashlib
import json
import re
import subprocess
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from specui.models import Cell, RunKind, RunRecord

# Status cuja célula NÃO está concluída: o `run` seguinte a executa de novo.
RETRY_STATUSES = frozenset({"api_error", "model_mismatch"})

_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def make_run_id(cell: Cell, now: datetime | None = None) -> str:
    """`<prompt>__<modalidade>__<provedor>__r<rep>__<AAAAMMDDTHHMMSS>`, seguro para diretório."""
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%S")
    prompt = _SAFE.sub("-", cell.prompt_source.prompt_id).strip("-")
    return f"{prompt}__{cell.modality}__{cell.provider}__r{cell.rep}__{stamp}"


def short_workspace_id(run_id: str) -> str:
    """Nome curto (cabe no MAX_PATH do Windows) para o diretório de build do harness."""
    return "w" + hashlib.sha1(run_id.encode("utf-8")).hexdigest()[:10]


def repo_commit(repo_root: str | Path) -> str | None:
    """Commit atual (curto), com sufixo `+dirty` se houver mudanças fora de results/."""
    root = str(repo_root)
    try:
        sha = subprocess.run(
            ["git", "-C", root, "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", root, "status", "--porcelain", "--", ".", ":(exclude)results"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return f"{sha}+dirty" if dirty else sha


class RunStore:
    def __init__(self, results_dir: str | Path, run_kind: RunKind = "main") -> None:
        base = Path(results_dir)
        self.root = base / "pilot" if run_kind == "pilot" else base
        self.runs_dir = self.root / "runs"
        self.manifest_path = self.root / "manifest.jsonl"
        self.run_kind = run_kind

    # ------------------------------------------------------------------ escrita

    def run_dir(self, run_id: str) -> Path:
        path = self.runs_dir / run_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def artifact(self, rec: RunRecord, key: str) -> Path:
        """Caminho absoluto de um artefato registrado em `rec.paths` (que é relativo)."""
        return self.root / rec.paths["run_dir"] / rec.paths[key]

    def save_record(self, rec: RunRecord) -> Path:
        path = self.run_dir(rec.run_id) / "record.json"
        path.write_text(
            json.dumps(rec.model_dump(mode="json", by_alias=True), ensure_ascii=False, indent=2),
            encoding="utf-8", newline="\n",
        )
        return path

    def append_manifest(self, rec: RunRecord) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        entry = {
            "run_id": rec.run_id,
            "cell_key": rec.cell_key,
            "status": rec.status,
            "created_at": rec.created_at,
            "record_path": (self.runs_dir / rec.run_id / "record.json").relative_to(self.root).as_posix(),
        }
        with open(self.manifest_path, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def save(self, rec: RunRecord) -> None:
        """Grava o record e registra a tentativa no manifest."""
        self.save_record(rec)
        self.append_manifest(rec)

    # ------------------------------------------------------------------ metadados congelados

    @property
    def meta_path(self) -> Path:
        return self.root / "run_meta.json"

    def read_meta(self) -> dict[str, Any] | None:
        return json.loads(self.meta_path.read_text(encoding="utf-8")) if self.meta_path.is_file() else None

    def freeze_meta(self, equivalence_margin: float | None, config_sha256: str) -> dict[str, Any]:
        """Grava (uma vez) o que não pode mudar durante a execução principal. Se já existe, confere:
        a margem de equivalência diferente do congelado levanta ValueError."""
        existing = self.read_meta()
        if existing is not None:
            if existing.get("equivalence_margin") != equivalence_margin:
                raise ValueError(
                    f"analysis.equivalence_margin mudou depois do congelamento "
                    f"({existing.get('equivalence_margin')} -> {equivalence_margin})"
                )
            return existing
        meta = {"equivalence_margin": equivalence_margin, "config_sha256": config_sha256,
                "frozen_at": datetime.now(UTC).isoformat(timespec="seconds")}
        self.root.mkdir(parents=True, exist_ok=True)
        self.meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
        return meta

    # ------------------------------------------------------------------ leitura

    def manifest(self) -> list[dict[str, Any]]:
        if not self.manifest_path.is_file():
            return []
        with open(self.manifest_path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def latest_status(self) -> dict[str, str]:
        """cell_key -> status da última tentativa."""
        return {e["cell_key"]: e["status"] for e in self.manifest()}

    def completed_keys(self) -> set[str]:
        """Células já concluídas (a última tentativa não é api_error nem model_mismatch)."""
        return {k for k, status in self.latest_status().items() if status not in RETRY_STATUSES}

    def load_records(self) -> list[RunRecord]:
        """Um record por célula: o da última tentativa registrada no manifest."""
        last: dict[str, str] = {e["cell_key"]: e["run_id"] for e in self.manifest()}
        records: list[RunRecord] = []
        for run_id in last.values():
            path = self.runs_dir / run_id / "record.json"
            if path.is_file():
                records.append(RunRecord.model_validate_json(path.read_text(encoding="utf-8")))
        return records


# ---------------------------------------------------------------------- tabelas


def _flatten(prefix: str, value: Any, out: dict[str, Any]) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            _flatten(f"{prefix}_{k}" if prefix else str(k), v, out)
    elif isinstance(value, list):
        out[prefix] = json.dumps(value, ensure_ascii=False) if value else None
        if all(isinstance(x, str) for x in value):
            out[f"{prefix}_n"] = len(value)
    else:
        out[prefix] = value


def flatten_record(rec: RunRecord) -> dict[str, Any]:
    """Uma linha por execução. Grupos viram prefixos (exec_, d2c_, cq_, fn_, tech_, in_, cost_)."""
    data = rec.model_dump(mode="json", by_alias=True)
    groups = {
        "exec": "exec", "design2code": "d2c", "embeddings": "emb", "code_quality": "cq",
        "functional": "fn", "technical": "tech", "input_spec": "in", "cost": "cost",
    }
    row: dict[str, Any] = {}
    for key, value in data.items():
        if key in groups:
            if value is not None:
                _flatten(groups[key], value, row)
        elif key in ("paths", "errors", "thinking"):
            row[key] = json.dumps(value, ensure_ascii=False) if value else None
        else:
            row[key] = value
    row.pop("fn_cases", None)  # detalhe por caso fica no record.json
    return row


def records_to_dataframe(records: Iterable[RunRecord]) -> pd.DataFrame:
    rows = [flatten_record(r) for r in records]
    return pd.DataFrame(rows)


def _as_float(series: pd.Series) -> pd.Series | None:
    """Série numérica ou booleana (com ausentes) como float; None para o resto (texto, listas)."""
    if pd.api.types.is_bool_dtype(series) or pd.api.types.is_numeric_dtype(series):
        return series.astype("float64")
    values = series.dropna()
    if len(values) and all(isinstance(v, bool) for v in values):
        return series.map(lambda v: float(v) if isinstance(v, bool) else float("nan"))
    return None


def to_long(df: pd.DataFrame) -> pd.DataFrame:
    """Formato longo (run_id, ..., metric, value) só com colunas numéricas/booleanas (0/1).
    Valores ausentes ficam de fora: métrica não calculada nunca vira 0."""
    id_cols = [c for c in ("run_id", "task_id", "prompt_kind", "modality", "provider",
                           "model_id_requested", "rep", "status") if c in df]
    metrics: dict[str, pd.Series] = {}
    for col in df.columns:
        if col in id_cols or col.endswith("_n") and col[:-2] in df:
            continue
        converted = _as_float(df[col])
        if converted is not None:
            metrics[col] = converted
    wide = pd.concat([df[id_cols], pd.DataFrame(metrics)], axis=1)
    long = wide.melt(id_vars=id_cols, value_vars=list(metrics), var_name="metric", value_name="value")
    return long.dropna(subset=["value"])


def write_aggregate(df: pd.DataFrame, out_dir: str | Path) -> dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {"runs": out / "runs.parquet", "metrics_long": out / "metrics_long.csv"}
    df.to_parquet(paths["runs"], index=False)
    to_long(df).to_csv(paths["metrics_long"], index=False, encoding="utf-8")
    return paths
