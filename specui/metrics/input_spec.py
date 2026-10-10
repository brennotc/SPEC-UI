"""Métricas do insumo: o quanto o texto do prompt especifica (calculado para TODO prompt).

Tudo por regex, determinístico. O grau de especificação é uma variável medida no texto,
não um rótulo; é o que permite analisar prompts livres de participantes.
"""

import re
from collections.abc import Iterable
from typing import Any

from specui.models import InputSpecMetrics, RequirementCoverage, StackRequests

_HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{3}){1,2}\b")
_PX_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s?px\b", re.IGNORECASE)
_DEFAULTS_RE = re.compile(r"\b(?:default|padr[ãa]o|por\s+padr[ãa]o)\b", re.IGNORECASE)
_ARIA_RE = re.compile(r"\baria-[a-z]+", re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"</?[a-z][a-z0-9-]*(?:\s[^<>]*)?/?>", re.IGNORECASE)

_LIST_RE = re.compile(r"^\s*[-*+]\s+\S", re.MULTILINE)
_NUMBERING_RE = re.compile(r"^\s*\d+[.)]\s+\S", re.MULTILINE)
_HEADING_RE = re.compile(r"^\s*#{1,6}\s+\S", re.MULTILINE)
_FENCE_RE = re.compile(r"^\s*```", re.MULTILINE)
_TYPE_DECL_RE = re.compile(r"\b(?:interface|type|enum)\s+[A-Z]\w*")

_IMAGE_REF_RE = re.compile(
    r"\bcomo\s+(?:na|no)\s+(?:imagem|design|figma|prot[óo]tipo|layout)\b"
    r"|\bigual\s+(?:à|a|ao)\s+(?:imagem|design|figma|prot[óo]tipo|layout)\b"
    r"|\bconforme\s+(?:a\s+|o\s+)?(?:imagem|design|figma|prot[óo]tipo|layout)\b"
    r"|\bsegundo\s+(?:a\s+|o\s+)?(?:imagem|design|figma|prot[óo]tipo)\b"
    r"|\b(?:na|da|pela)\s+imagem\b"
    r"|\b(?:no|do|pelo)\s+(?:design|figma)\b"
    r"|\bimagem\s+(?:anexa|anexada|fornecida|enviada)\b"
    r"|\bem\s+anexo\b",
    re.IGNORECASE,
)

# Menções a outras tecnologias (o envelope manda a stack fixa prevalecer; isto mede o pedido).
_STACK_PATTERNS: dict[str, re.Pattern[str]] = {
    "react": re.compile(r"\breact(?:\.?js)?\b|\bjsx\b|\btsx\b", re.IGNORECASE),
    "vue": re.compile(r"\bvue(?:\.?js)?\b|\bnuxt\b", re.IGNORECASE),
    "svelte": re.compile(r"\bsvelte(?:kit)?\b", re.IGNORECASE),
    "next": re.compile(r"\bnext\.?js\b", re.IGNORECASE),
    "html_puro": re.compile(
        r"\bhtml\s+puro\b|\bapenas\s+html\b|\bsomente\s+html\b|\bs[óo]\s+html\b|\bvanilla\b"
        r"|\bjavascript\s+puro\b|\bjs\s+puro\b|\bhtml\s*/\s*css\b|\bhtml,?\s+css\s+e\s+(?:js|javascript)\b",
        re.IGNORECASE,
    ),
    "bootstrap": re.compile(r"\bbootstrap\b", re.IGNORECASE),
    "jquery": re.compile(r"\bjquery\b", re.IGNORECASE),
}
_OTHER_STACK_PATTERNS: dict[str, re.Pattern[str]] = {
    "material_ui": re.compile(r"\bmaterial[\s-]?ui\b|\bmui\b", re.IGNORECASE),
    "chakra": re.compile(r"\bchakra\b", re.IGNORECASE),
    "styled_components": re.compile(r"\bstyled[\s-]?components\b", re.IGNORECASE),
    "sass": re.compile(r"\bsass\b|\bscss\b", re.IGNORECASE),
    "flutter": re.compile(r"\bflutter\b", re.IGNORECASE),
    "python_flask": re.compile(r"\bflask\b|\bdjango\b|\bstreamlit\b", re.IGNORECASE),
    "node_backend": re.compile(r"\bexpress(?:\.?js)?\b|\bnode\.?js\b", re.IGNORECASE),
}


def constraint_density(text: str) -> dict[str, int]:
    """Contagem de restrições explícitas no texto."""
    return {
        "hex": len(_HEX_RE.findall(text)),
        "px": len(_PX_RE.findall(text)),
        "defaults": len(_DEFAULTS_RE.findall(text)),
        "aria": len(_ARIA_RE.findall(text)),
        "html_tags": len(_HTML_TAG_RE.findall(text)),
    }


def structure_markers(text: str) -> dict[str, int]:
    return {
        "lists": len(_LIST_RE.findall(text)),
        "numbering": len(_NUMBERING_RE.findall(text)),
        "headings": len(_HEADING_RE.findall(text)),
        "code_blocks": len(_FENCE_RE.findall(text)) // 2,
        "type_decls": len(_TYPE_DECL_RE.findall(text)),
    }


def image_references(text: str) -> int:
    return len(_IMAGE_REF_RE.findall(text))


def stack_requests(text: str) -> StackRequests:
    found = {name: bool(p.search(text)) for name, p in _STACK_PATTERNS.items()}
    outros = [name for name, p in _OTHER_STACK_PATTERNS.items() if p.search(text)]
    return StackRequests(**found, outros=outros)


def requirement_coverage(text: str, requirements: Iterable[Any]) -> RequirementCoverage:
    """Fração de requisitos mencionados no texto, no total e por `info_source`.

    Cada requisito precisa de `id`, `info_source` e `mention_patterns` (lista de regex), como em
    oracles/<tarefa>/requirements.yaml. Aceita dicts ou objetos. Requisitos sem padrões não contam.
    """
    totals: dict[str, int] = {}
    hits: dict[str, int] = {}
    for req in requirements:
        get = req.get if isinstance(req, dict) else lambda k, d=None, _r=req: getattr(_r, k, d)
        patterns = get("mention_patterns") or []
        if not patterns:
            continue
        source = get("info_source") or "behavior"
        totals[source] = totals.get(source, 0) + 1
        if any(re.search(p, text, flags=re.IGNORECASE) for p in patterns):
            hits[source] = hits.get(source, 0) + 1
    if not totals:
        return RequirementCoverage()
    all_total = sum(totals.values())
    return RequirementCoverage(
        total=sum(hits.values()) / all_total,
        by_info_source={src: hits.get(src, 0) / n for src, n in totals.items()},
    )


def compute_input_spec(
    text: str,
    requirements: Iterable[Any] | None = None,
    envelope_chars: int = 0,
) -> InputSpecMetrics:
    return InputSpecMetrics(
        chars=len(text),
        words=len(text.split()),
        constraint_density=constraint_density(text),
        requirement_coverage=requirement_coverage(text, requirements or []),
        structure_markers=structure_markers(text),
        image_references=image_references(text),
        stack_requests=stack_requests(text),
        envelope_chars=envelope_chars,
    )
