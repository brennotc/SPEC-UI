"""Fontes de prompt (no_spec, with_spec, free) e importador de prompts livres de participantes.

Coletas de prompts livres são ANÔNIMAS: ids sequenciais (p001...), nenhuma tabela de identidade,
perfil só em faixas amplas. A remoção de PII no texto continua (texto livre pode conter dados
identificáveis por acidente) e cada remoção é listada em import_report.md para revisão.
"""

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from specui.models import PromptSource, RunConfig, Task
from specui.tasks import sha256_text

# --------------------------------------------------------------------------- fontes padrão


def make_standard_source(task: Task, kind: str) -> PromptSource:
    """no_spec = só '## Prompt'; with_spec = só '## Specification'."""
    if kind == "no_spec":
        text = task.prompt_text
    elif kind == "with_spec":
        text = task.spec_text
    else:
        raise ValueError(f"fonte padrão inválida: {kind}")
    return PromptSource(
        kind=kind,  # type: ignore[arg-type]
        prompt_id=f"{task.id}/{kind}",
        task_id=task.id,
        text=text,
        text_sha256=sha256_text(text),
    )


def load_collection(collection_dir: Path) -> dict[str, Any]:
    """Lê collection.yaml e exige coleta anônima com participantes informados."""
    path = collection_dir / "collection.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"collection.yaml não encontrado em {collection_dir}")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if data.get("anonymous") is not True:
        raise ValueError(f"{path}: 'anonymous: true' é obrigatório (coleta anônima)")
    if data.get("participants_informed") is not True:
        raise ValueError(
            f"{path}: 'participants_informed: true' é obrigatório "
            "(o formulário informa o uso e a possível publicação anônima dos textos)"
        )
    return data


def load_free_sources(
    benchmarks_dir: Path, collection_id: str, valid_task_ids: set[str] | None = None
) -> list[PromptSource]:
    """Lê benchmarks/free_prompts/<coleta>/prompts.jsonl como PromptSource(kind='free')."""
    collection_dir = benchmarks_dir / "free_prompts" / collection_id
    collection = load_collection(collection_dir)
    jsonl = collection_dir / "prompts.jsonl"
    if not jsonl.is_file():
        raise FileNotFoundError(f"prompts.jsonl não encontrado em {collection_dir}")
    sources: list[PromptSource] = []
    with open(jsonl, encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            task_id = rec["task_id"]
            if valid_task_ids is not None and task_id not in valid_task_ids:
                continue
            text = rec["text"]
            sources.append(
                PromptSource(
                    kind="free",
                    prompt_id=f"free:{collection_id}/{rec['participant_id']}/{rec.get('n', line_no)}",
                    task_id=task_id,
                    text=text,
                    text_sha256=rec.get("text_sha256") or sha256_text(text),
                    collection_id=collection_id,
                    participant_id=rec["participant_id"],
                    intended_modality=rec.get("intended_modality"),
                    material_shown=collection.get("material_shown"),
                    collected_at=rec.get("collected_at"),
                    instrument_version=str(collection.get("instrument_version") or "") or None,
                    metadata={k: str(v) for k, v in (rec.get("profile") or {}).items()},
                )
            )
    return sources


def resolve_prompt_sources(cfg: RunConfig, tasks: list[Task]) -> list[PromptSource]:
    """Expande cfg.prompt_sources em PromptSource, só para as tarefas carregadas."""
    task_ids = {t.id for t in tasks}
    sources: list[PromptSource] = []
    for entry in cfg.prompt_sources:
        if entry in ("no_spec", "with_spec"):
            sources.extend(make_standard_source(t, entry) for t in tasks)
        else:
            collection_id = entry.split(":", 1)[1]
            sources.extend(load_free_sources(cfg.path("benchmarks_dir"), collection_id, task_ids))
    return sources


# --------------------------------------------------------------------------- remoção de PII

_NAME = r"[A-ZÀ-Ý][A-Za-zÀ-ÿ'-]+(?:\s+[A-ZÀ-Ý][A-Za-zÀ-ÿ'-]+){0,3}"
_PII_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("email", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[EMAIL]"),
    ("cpf", re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"), "[CPF]"),
    (
        "telefone",
        re.compile(r"(?:\+55\s?)?\(?\d{2}\)?[\s-]?9?\d{4}[-\s]\d{4}\b"),
        "[TELEFONE]",
    ),
    (
        "url_perfil",
        re.compile(
            r"(?:https?://)?(?:www\.)?(?:linkedin|github|instagram|facebook|twitter|x)\.com/\S+",
            re.IGNORECASE,
        ),
        "[URL_PERFIL]",
    ),
]
_NAME_INTRO = re.compile(rf"((?i:\bmeu\s+nome\s+[ée]|\bme\s+chamo|\bsou\s+(?:o|a)))(\s+)({_NAME})")


@dataclass
class Redaction:
    row: int
    task_id: str | None
    category: str
    context: str  # trecho já anonimizado ao redor do marcador


def redact_pii(text: str, redact_terms: list[str] | None = None) -> tuple[str, list[tuple[str, str]]]:
    """Remove PII do texto. Devolve (texto_limpo, [(categoria, marcador), ...]) em ordem de uso."""
    found: list[tuple[str, str]] = []
    for category, pattern, token in _PII_PATTERNS:
        text, n = pattern.subn(token, text)
        found.extend([(category, token)] * n)

    def _name(m: re.Match[str]) -> str:
        found.append(("nome", "[NOME]"))
        return f"{m.group(1)}{m.group(2)}[NOME]"

    text = _NAME_INTRO.sub(_name, text)
    for term in redact_terms or []:
        if not term.strip():
            continue
        text, n = re.subn(rf"\b{re.escape(term)}\b", "[REMOVIDO]", text, flags=re.IGNORECASE)
        found.extend([("termo", "[REMOVIDO]")] * n)
    return text, found


def _contexts(clean_text: str, found: list[tuple[str, str]], width: int = 25) -> list[str]:
    """Janelas ±width ao redor de cada marcador, no texto já limpo (sem PII)."""
    positions: dict[str, list[int]] = {}
    out: list[str] = []
    for _, token in found:
        starts = positions.setdefault(token, [m.start() for m in re.finditer(re.escape(token), clean_text)])
        idx = starts.pop(0) if starts else clean_text.find(token)
        lo, hi = max(0, idx - width), min(len(clean_text), idx + len(token) + width)
        out.append(("…" if lo else "") + clean_text[lo:hi].replace("\n", " ") + ("…" if hi < len(clean_text) else ""))
    return out


# --------------------------------------------------------------------------- importador


@dataclass
class ImportResult:
    accepted: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)  # row, task_id, reason
    redactions: list[Redaction] = field(default_factory=list)
    ignored_columns: list[str] = field(default_factory=list)


def _norm_date(value: str | None) -> str | None:
    """Reduz o carimbo de data/hora à data (AAAA-MM-DD): hora exata é identificável demais."""
    if not value:
        return None
    value = value.strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", value)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", value)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return None


def import_free_prompts(
    collection_dir: str | Path,
    csv_path: str | Path,
    map_path: str | Path,
    valid_task_ids: set[str],
    write: bool = True,
) -> ImportResult:
    """Importa respostas do formulário para <coleta>/prompts.jsonl + import_report.md.

    Exige collection.yaml com anonymous e participants_informed. Só lê as colunas mapeadas;
    qualquer outra é ignorada (e listada). Nunca grava nome, e-mail ou tabela de identidade.
    """
    collection_dir = Path(collection_dir)
    load_collection(collection_dir)  # recusa coleta não anônima / sem aviso aos participantes
    with open(map_path, encoding="utf-8") as f:
        mapping = yaml.safe_load(f) or {}

    columns: dict[str, Any] = mapping.get("columns") or {}
    profile_cols: dict[str, str] = mapping.get("profile") or {}
    bands: dict[str, list[str]] = mapping.get("profile_bands") or {}
    task_values: dict[str, str] = mapping.get("task_values") or {}
    modality_values = {str(k).strip().lower(): v for k, v in (mapping.get("modality_values") or {}).items()}
    drop: list[str] = list(mapping.get("drop") or [])
    redact_terms: list[str] = list(mapping.get("redact_terms") or [])
    min_chars: int = int(mapping.get("min_chars", 20))
    delimiter: str = mapping.get("delimiter", ",")

    wide: dict[str, str] = columns.get("task_columns") or {}
    long_task_col, long_text_col = columns.get("task"), columns.get("text")
    if not wide and not (long_task_col and long_text_col):
        raise ValueError("map.yaml precisa de columns.task_columns (largo) ou columns.task + columns.text (longo)")
    modality_col, date_col = columns.get("intended_modality"), columns.get("collected_at")

    mapped = set(wide.values()) | set(profile_cols.values())
    mapped |= {c for c in (long_task_col, long_text_col, modality_col, date_col) if c}
    forbidden = mapped & set(drop)
    if forbidden:
        raise ValueError(f"colunas mapeadas também estão em 'drop': {sorted(forbidden)}")

    result = ImportResult()
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        header = list(reader.fieldnames or [])
        missing = mapped - set(header)
        if missing:
            raise ValueError(f"colunas do map.yaml ausentes no CSV: {sorted(missing)}")
        result.ignored_columns = [c for c in header if c not in mapped]
        rows = list(reader)

    seen_hashes: set[str] = set()
    participant_n = 0
    for row_no, row in enumerate(rows, start=2):  # linha 1 = cabeçalho
        candidates: list[tuple[str | None, str]] = []
        if wide:
            for task_id, col in wide.items():
                candidates.append((task_id, row.get(col) or ""))
        else:
            raw_task = (row.get(long_task_col) or "").strip()
            candidates.append((task_values.get(raw_task, raw_task) or None, row.get(long_text_col) or ""))

        modality: str | None = None
        if modality_col:
            raw_mod = (row.get(modality_col) or "").strip().lower()
            modality = modality_values.get(raw_mod, raw_mod if raw_mod in ("text", "multimodal") else None)

        profile: dict[str, str] = {}
        profile_error: str | None = None
        for fld, col in profile_cols.items():
            value = (row.get(col) or "").strip()
            if not value:
                continue
            if fld in bands and value not in bands[fld]:
                profile_error = f"profile_out_of_band:{fld}"
                break
            profile[fld] = value

        pending: list[dict[str, Any]] = []
        for task_id, raw_text in candidates:
            text = raw_text.strip()
            if wide and not text:
                continue  # coluna de tarefa não respondida no formato largo
            if not text:
                result.rejected.append({"row": row_no, "task_id": task_id, "reason": "empty"})
                continue
            if task_id not in valid_task_ids:
                result.rejected.append({"row": row_no, "task_id": task_id, "reason": "unknown_task"})
                continue
            if modality_col and modality is None:
                result.rejected.append({"row": row_no, "task_id": task_id, "reason": "invalid_modality"})
                continue
            if profile_error:
                result.rejected.append({"row": row_no, "task_id": task_id, "reason": profile_error})
                continue
            clean, found = redact_pii(text, redact_terms)
            if len(clean) < min_chars:
                result.rejected.append({"row": row_no, "task_id": task_id, "reason": "too_short"})
                continue
            digest = sha256_text(clean)
            if digest in seen_hashes:
                result.rejected.append({"row": row_no, "task_id": task_id, "reason": "duplicate"})
                continue
            seen_hashes.add(digest)
            for (category, _), ctx in zip(found, _contexts(clean, found)):
                result.redactions.append(Redaction(row_no, task_id, category, ctx))
            pending.append({"task_id": task_id, "text": clean, "text_sha256": digest})

        if not pending:
            continue
        participant_n += 1
        pid = f"p{participant_n:03d}"
        for n, item in enumerate(pending, start=1):
            result.accepted.append(
                {
                    "participant_id": pid,
                    "task_id": item["task_id"],
                    "n": n,
                    "text": item["text"],
                    "text_sha256": item["text_sha256"],
                    "intended_modality": modality,
                    "collected_at": _norm_date(row.get(date_col)) if date_col else None,
                    "profile": profile,
                }
            )

    if write:
        _write_import_outputs(collection_dir, result, Path(csv_path).name)
    return result


def _write_import_outputs(collection_dir: Path, result: ImportResult, csv_name: str) -> None:
    with open(collection_dir / "prompts.jsonl", "w", encoding="utf-8", newline="\n") as f:
        f.writelines(json.dumps(rec, ensure_ascii=False) + "\n" for rec in result.accepted)

    lines = [
        "# Relatório de importação",
        "",
        f"- Arquivo de origem: `{csv_name}` (não é copiado para o repositório)",
        (
            f"- Prompts aceitos: {len(result.accepted)} "
            f"({len({r['participant_id'] for r in result.accepted})} participantes)"
        ),
        f"- Prompts rejeitados: {len(result.rejected)}",
        f"- Remoções de PII: {len(result.redactions)} (revise a lista abaixo)",
        "",
        "## Colunas ignoradas (nunca lidas)",
        "",
        *([f"- {c}" for c in result.ignored_columns] or ["- (nenhuma)"]),
        "",
        "## Rejeitados",
        "",
        "| linha | tarefa | motivo |",
        "|---|---|---|",
        *[f"| {r['row']} | {r['task_id']} | {r['reason']} |" for r in result.rejected],
        "",
        "## Remoções de PII (contexto já anonimizado)",
        "",
        "| linha | tarefa | categoria | contexto |",
        "|---|---|---|---|",
        *[f"| {r.row} | {r.task_id} | {r.category} | {r.context} |" for r in result.redactions],
        "",
    ]
    (collection_dir / "import_report.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
