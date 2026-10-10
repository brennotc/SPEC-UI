"""Parser da resposta do modelo: blocos de código cercados com o caminho do arquivo.

Formato exigido pelo envelope:

    ```ts file=src/app/app.ts
    ...conteúdo...
    ```

Tolerâncias: fim de linha CRLF, cerca externa envolvendo toda a resposta, atributos
`path=`/`title=`/`filename=`, e primeira linha `// FILE: caminho` (ou `<!-- FILE: ... -->`,
`/* FILE: ... */`). Resposta sem nenhum bloco válido = falha de FORMATO (separada de build).
"""

import hashlib
import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

MAX_FILES = 60
MAX_TOTAL_BYTES = 2 * 1024 * 1024

_FENCE_OPEN = re.compile(r"^[ \t]*(?P<ticks>`{3,}|~{3,})(?P<info>[^\n]*)$")
_ATTR = re.compile(
    r"""(?:file|path|title|filename)\s*=\s*(?:"(?P<dq>[^"]+)"|'(?P<sq>[^']+)'|(?P<bare>[^\s"']+))""",
    re.IGNORECASE,
)
_HEADER_COMMENT = re.compile(
    r"^\s*(?://|/\*|<!--)\s*FILE:\s*(?P<path>[^\s*>]+)\s*(?:\*/|-->)?\s*$", re.IGNORECASE
)
_ALLOWED_APP = re.compile(r"^src/app/[A-Za-z0-9_./-]+\.(?:ts|html|css)$")
_ROOT_COMPONENT = re.compile(r"\bexport\s+class\s+App\b")
_OUTER_INFOS = {"", "markdown", "md", "text", "txt"}

ALLOWED_STYLES = "src/styles.css"
ROOT_COMPONENT_PATH = "src/app/app.ts"


class PathRejected(ValueError):
    """Caminho fora da política; a mensagem é o motivo registrado em `files_rejected`."""


def validate_path(raw: str) -> str:
    """Normaliza e valida o caminho de um arquivo gerado. Levanta PathRejected com o motivo."""
    path = raw.strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    if not path:
        raise PathRejected("caminho vazio")
    if "\x00" in path:
        raise PathRejected("caminho com byte nulo")
    if path.startswith("/") or re.match(r"^[A-Za-z]:", path):
        raise PathRejected("caminho absoluto")
    segments = path.split("/")
    if ".." in segments:
        raise PathRejected("contém '..'")
    if "//" in path or "" in segments:
        raise PathRejected("segmento vazio no caminho")
    if path == ALLOWED_STYLES:
        return path
    if path.endswith(".spec.ts"):
        raise PathRejected("arquivo de teste (.spec.ts)")
    if not _ALLOWED_APP.match(path):
        raise PathRejected("fora das áreas permitidas (src/app/**/*.{ts,html,css} ou src/styles.css)")
    return path


class GeneratedFile(BaseModel):
    path: str
    content: str
    sha256: str


class GeneratedBundle(BaseModel):
    files: list[GeneratedFile] = Field(default_factory=list)
    rejected: list[tuple[str, str]] = Field(default_factory=list)  # (caminho, motivo)
    duplicates: list[str] = Field(default_factory=list)  # caminhos repetidos (vale o último)
    warnings: list[str] = Field(default_factory=list)
    format_ok: bool = False  # ≥1 bloco com caminho válido
    contract_ok: bool = False  # src/app/app.ts com `export class App`
    parser_used: Literal["fence_attr", "fence_comment", "none"] = "none"


@dataclass
class _Block:
    info: str
    lines: list[str]
    closed: bool


def _closing_re(ticks: str) -> re.Pattern[str]:
    return re.compile(rf"^[ \t]*{re.escape(ticks[0])}{{{len(ticks)},}}[ \t]*$")


def _extract_blocks(lines: list[str]) -> list[_Block]:
    blocks: list[_Block] = []
    i, n = 0, len(lines)
    while i < n:
        m = _FENCE_OPEN.match(lines[i])
        if not m:
            i += 1
            continue
        closing = _closing_re(m.group("ticks"))
        j = i + 1
        while j < n and not closing.match(lines[j]):
            j += 1
        blocks.append(_Block(m.group("info").strip(), lines[i + 1 : j], closed=j < n))
        i = j + 1
    return blocks


def _strip_outer_wrapper(lines: list[str]) -> list[str]:
    """Remove uma cerca externa (sem caminho) que envolve a resposta inteira."""
    nonempty = [k for k, line in enumerate(lines) if line.strip()]
    if len(nonempty) < 3:
        return lines
    first, last = nonempty[0], nonempty[-1]
    m = _FENCE_OPEN.match(lines[first])
    if not m or _ATTR.search(m.group("info")) or m.group("info").strip().lower() not in _OUTER_INFOS:
        return lines
    if not _closing_re(m.group("ticks")).match(lines[last]):
        return lines
    inner = lines[first + 1 : last]
    has_inner_file = any(
        (im := _FENCE_OPEN.match(line)) and _ATTR.search(im.group("info")) for line in inner
    )
    return inner if has_inner_file else lines


def parse_bundle(text: str) -> GeneratedBundle:
    """Extrai os arquivos da resposta do modelo e valida os caminhos."""
    bundle = GeneratedBundle()
    lines = _strip_outer_wrapper(text.replace("\r\n", "\n").replace("\r", "\n").split("\n"))

    found: dict[str, str] = {}  # caminho -> conteúdo (último vence)
    used_attr = used_comment = False
    total_bytes = 0
    for block in _extract_blocks(lines):
        content_lines = list(block.lines)
        raw_path: str | None = None
        attr = _ATTR.search(block.info)
        if attr:
            raw_path = attr.group("dq") or attr.group("sq") or attr.group("bare")
            from_attr = True
        else:
            from_attr = False
            if content_lines and (hm := _HEADER_COMMENT.match(content_lines[0])):
                raw_path = hm.group("path")
                content_lines = content_lines[1:]
        if raw_path is None:
            continue  # bloco sem caminho (ex.: exemplo solto): não é arquivo

        try:
            path = validate_path(raw_path)
        except PathRejected as exc:
            bundle.rejected.append((raw_path, str(exc)))
            continue
        content = "\n".join(content_lines).rstrip("\n") + "\n"
        if not block.closed:
            bundle.warnings.append(f"bloco de '{path}' não foi fechado (possível truncamento)")
        if path in found:
            bundle.duplicates.append(path)
        elif len(found) >= MAX_FILES:
            bundle.rejected.append((path, f"mais de {MAX_FILES} arquivos"))
            continue
        total_bytes += len(content.encode("utf-8"))
        if total_bytes > MAX_TOTAL_BYTES:
            bundle.rejected.append((path, "limite total de 2 MB excedido"))
            continue
        found[path] = content
        used_attr, used_comment = used_attr or from_attr, used_comment or not from_attr

    bundle.files = [
        GeneratedFile(path=p, content=c, sha256=hashlib.sha256(c.encode("utf-8")).hexdigest())
        for p, c in found.items()
    ]
    bundle.format_ok = bool(bundle.files)
    bundle.parser_used = "fence_attr" if used_attr else ("fence_comment" if used_comment else "none")
    root = found.get(ROOT_COMPONENT_PATH)
    bundle.contract_ok = bool(root and _ROOT_COMPONENT.search(root))
    return bundle
