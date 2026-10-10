"""Qualidade do código gerado (Figma2Code, ICLR 2026), calculada sobre o DOM renderizado e o CSS.

    RUR  unidades relativas nas declarações de layout (↑)      APR  posicionamento absoluto (↓)
    FU   containers com flex/grid (↑)                          BC   faixas de viewport cobertas (↑)
    STR  elementos semânticos (↑)                              AVU  classes de valor arbitrário (↓)
    ISR  estilo inline (↓)                                     CCR  classes customizadas reutilizadas (↑)

Escopo: os elementos DENTRO de `app-root` (o próprio app-root não conta), sem `<svg>` nem seus
descendentes, ignorando as classes `ng-*` e `cdk-*` do Angular. As camadas `theme` e `base` do
Tailwind (variáveis e preflight) não são código do modelo e ficam de fora do CSS analisado.

Razões com denominador zero: nas métricas em que MENOS é melhor (APR, AVU, ISR) valem 0,0 (nada
a penalizar); nas em que MAIS é melhor (RUR, FU, STR, CCR) ficam None (não há o que medir).
Todos os numeradores e denominadores vão em `counts`, para auditoria.
"""

import re
from collections import Counter
from collections.abc import Iterable
from typing import Any

from specui.models import CodeQualityMetrics

SEMANTIC_TAGS = frozenset({
    "header", "nav", "main", "section", "article", "aside", "footer",
    "h1", "h2", "h3", "h4", "h5", "h6", "p", "ul", "ol", "li", "button", "label", "input", "select",
    "textarea", "form", "table", "thead", "tbody", "tr", "th", "td", "figure", "figcaption", "time", "a", "dialog",
})
FLEX_GRID = frozenset({"flex", "inline-flex", "grid", "inline-grid"})
SKIPPED_LAYERS = frozenset({"theme", "base"})  # variáveis do tema e preflight: não são código do modelo
TAILWIND_LAYERS = frozenset({"theme", "base", "components", "utilities"})
BANDS = (("S", 0.0, 640.0), ("M", 640.0, 1024.0), ("L", 1024.0, 1280.0), ("XL", 1280.0, float("inf")))

_LAYOUT_PROP = re.compile(
    r"^(?:width|height|(?:min-|max-)(?:width|height)|(?:min-|max-)?(?:inline|block)-size|margin(?:-.+)?|"
    r"padding(?:-.+)?|top|right|bottom|left|inset(?:-.+)?|gap|row-gap|column-gap|"
    r"grid-template-(?:columns|rows)|grid-auto-(?:columns|rows)|flex-basis)$"
)
_RELATIVE_UNITS = {"%", "em", "rem", "ex", "ch", "vw", "vh", "vmin", "vmax", "svw", "svh", "lvw", "lvh",
                   "dvw", "dvh", "fr", "cqw", "cqh"}
_ABSOLUTE_UNITS = {"px", "pt", "pc", "cm", "mm", "in", "q"}
_LENGTH = re.compile(r"(-?(?:\d+\.?\d*|\.\d+))(%|[a-zA-Z]+)")
_VAR = re.compile(r"var\(\s*(--[\w-]+)\s*(?:,\s*((?:[^()]|\([^()]*\))*))?\)")
_CLASS_IN_SELECTOR = re.compile(r"\.((?:\\.|[\w-])+)")
_ARBITRARY = re.compile(r"\[[^\]]+\]")
_MEDIA_GROUP = re.compile(r"\(([^()]*)\)")
_MEDIA_LENGTH = re.compile(r"(\d*\.?\d+)\s*(px|rem|em)")


# ----------------------------------------------------------------------------- CSS

def parse_declarations(css_text: str) -> list[tuple[str, str]]:
    """`prop: valor; ...` -> [(prop, valor)], separando por `;` só fora de parênteses e aspas."""
    out: list[tuple[str, str]] = []
    depth, quote, start = 0, "", 0
    parts: list[str] = []
    for i, ch in enumerate(css_text):
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch == ";" and depth == 0:
            parts.append(css_text[start:i])
            start = i + 1
    parts.append(css_text[start:])
    for part in parts:
        prop, sep, value = part.partition(":")
        if sep and prop.strip():
            out.append((prop.strip().lower(), re.sub(r"\s*!important\s*$", "", value.strip(), flags=re.IGNORECASE)))
    return out


def _theme_variables(rules: Iterable[dict[str, Any]]) -> dict[str, str]:
    """Variáveis CSS globais (`--spacing: .25rem`, `--container-md: 28rem`...) para resolver var()."""
    variables: dict[str, str] = {}
    for rule in rules:
        selector = rule.get("selector") or ""
        if ":root" in selector or ":host" in selector or selector.strip() == "html":
            for prop, value in parse_declarations(rule.get("css_text", "")):
                if prop.startswith("--"):
                    variables[prop] = value
    return variables


def resolve_vars(value: str, variables: dict[str, str]) -> str:
    """Substitui var(--x[, fallback]) pelos valores do tema (até 6 níveis); sem valor, usa o fallback."""
    for _ in range(6):
        replaced = _VAR.sub(lambda m: variables.get(m.group(1)) or (m.group(2) or ""), value)
        if replaced == value:
            break
        value = replaced
    return value


def _top_level_tokens(value: str) -> list[str]:
    tokens, depth, current = [], 0, ""
    for ch in value:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch.isspace() and depth == 0:
            if current:
                tokens.append(current)
            current = ""
        else:
            current += ch
    if current:
        tokens.append(current)
    return tokens


def classify_length(value: str, variables: dict[str, str] | None = None) -> tuple[int, int]:
    """(nº de tokens relativos, nº de tokens absolutos) de um valor de layout.

    Um token é cada valor de topo (`calc(...)`, `1rem`, `50%`); zeros e palavras-chave (`auto`,
    `min-content`) não contam. Token com qualquer unidade relativa conta como relativo.
    """
    resolved = resolve_vars(value, variables or {})
    relative = absolute = 0
    for token in _top_level_tokens(resolved):
        units, numbers = set(), []
        for number, unit in _LENGTH.findall(token):
            unit = unit.lower()
            if unit in _RELATIVE_UNITS or unit in _ABSOLUTE_UNITS:
                units.add(unit)
                numbers.append(float(number))
        if not units or not any(n != 0 for n in numbers):
            continue
        if units & _RELATIVE_UNITS:
            relative += 1
        else:
            absolute += 1
    return relative, absolute


def class_names(selector: str) -> set[str]:
    """Classes citadas em um seletor (com o escape do Tailwind desfeito: `w-\\[123px\\]` -> `w-[123px]`)."""
    return {re.sub(r"\\(.)", r"\1", raw) for raw in _CLASS_IN_SELECTOR.findall(selector or "")}


_UPPER_BOUND = re.compile(r"(?:max-width\s*:|width\s*<=?)\s*$")  # texto antes do número: ele é um limite SUPERIOR


def media_boundaries(media: str | None) -> list[float]:
    """Larguras (px) que a media query usa como limite. `em`/`rem` valem 16px.

    Limite inferior (`min-width: X`, `width >= X`, `X <= width`) vale X. Limite superior (`max-width: X`, `width < X`,
    `width <= X`, o `B` de `A <= width < B`) vale X − 0,01: a query mira as larguras ABAIXO de X, então cai na faixa de baixo e
    não na que começa em X. Uma query negada (`not (min-width: 40rem)`, que o Tailwind emite para `max-sm:`) inverte o sentido de
    cada limite, em qualquer posição (`screen and not (...)`)."""
    if not media or "width" not in media:
        return []
    negated = re.search(r"\bnot\b", media) is not None
    bounds: list[float] = []
    for group in _MEDIA_GROUP.findall(media):
        if "width" not in group or "height" in group:
            continue
        for match in _MEDIA_LENGTH.finditer(group):
            number, unit = match.groups()
            px = float(number) * (1.0 if unit == "px" else 16.0)
            upper = _UPPER_BOUND.search(group[: match.start()]) is not None
            bounds.append(px - 0.01 if upper != negated else px)
    return bounds


def covered_bands(boundaries: Iterable[float]) -> set[str]:
    """Faixas S (<640), M (640-1023), L (1024-1279), XL (>=1280) com algum limite dentro."""
    covered = set()
    for bound in boundaries:
        for name, lo, hi in BANDS:
            if (lo < bound < hi) if name == "S" else (lo <= bound < hi):
                covered.add(name)
    return covered


# ----------------------------------------------------------------------------- métrica


def _ratio(numerator: int, denominator: int, empty: float | None) -> float | None:
    return numerator / denominator if denominator else empty


def compute_code_quality(snapshot: dict[str, Any]) -> CodeQualityMetrics:
    """RUR, APR, FU, BC, STR, AVU, ISR e CCR a partir do `css_snapshot.json`."""
    all_elements = snapshot.get("elements") or []
    if not all_elements:
        raise ValueError("snapshot sem elementos (app-root não renderizou?)")
    rules = snapshot.get("rules") or []
    variables = _theme_variables(rules)

    # escopo: descendentes de app-root (o primeiro elemento), sem svg
    elements = [e for e in all_elements[1:] if e["tag"] != "svg" and not e.get("in_svg")]
    tokens = [c for e in elements for c in e["classes"] if not c.startswith(("ng-", "cdk-"))]

    # --- CSS do app: tudo, menos as camadas theme/base do Tailwind
    app_rules = [r for r in rules if (r.get("layer") or "").split(".")[0] not in SKIPPED_LAYERS]

    rel = absolute = 0
    for rule in app_rules:
        for prop, value in parse_declarations(rule.get("css_text", "")):
            if _LAYOUT_PROP.match(prop):
                r, a = classify_length(value, variables)
                rel, absolute = rel + r, absolute + a

    positioned = [e for e in elements if e["position"] != "static"]
    absolutely = [e for e in positioned if e["position"] in ("absolute", "fixed")]
    containers = [e for e in elements if e["child_count"] >= 1]
    flex_grid = [e for e in containers if e["display"] in FLEX_GRID]
    semantic = [e for e in elements if e["tag"] in SEMANTIC_TAGS]
    arbitrary = [t for t in tokens if _ARBITRARY.search(t)]
    inline = [e for e in elements if e.get("inline_style")]

    boundaries = [b for r in app_rules for b in media_boundaries(r.get("media"))]
    bands = covered_bands(boundaries)

    # --- classes customizadas: definidas em CSS sem camada (global do modelo ou de componente)
    custom_defined: set[str] = set()
    tailwind_defined: set[str] = set()
    for rule in rules:
        layer = (rule.get("layer") or "").split(".")[0]
        if layer in TAILWIND_LAYERS:
            tailwind_defined |= class_names(rule.get("selector", ""))
        elif not layer:
            custom_defined |= class_names(rule.get("selector", ""))
    usage = Counter(t for t in tokens if t in custom_defined)
    reused = [name for name, n in usage.items() if n >= 2]
    undefined = {t for t in tokens if t not in custom_defined and t not in tailwind_defined}

    counts = {
        "layout_declarations_relative": rel, "layout_declarations_total": rel + absolute,
        "positioned_absolute": len(absolutely), "positioned_total": len(positioned),
        "containers_flex_grid": len(flex_grid), "containers_total": len(containers),
        "bands_covered": len(bands), "bands_total": len(BANDS),
        "semantic_elements": len(semantic), "elements_total": len(elements),
        "arbitrary_classes": len(arbitrary), "classes_total": len(tokens),
        "inline_style_elements": len(inline),
        "custom_classes_reused": len(reused), "custom_classes_used": len(usage),
        "custom_classes_dead": len(custom_defined - set(usage)), "classes_undefined": len(undefined),
    }
    return CodeQualityMetrics(
        rur=_ratio(rel, rel + absolute, None),
        apr=_ratio(len(absolutely), len(positioned), 0.0),
        fu=_ratio(len(flex_grid), len(containers), None),
        bc=len(bands) / len(BANDS),
        str=_ratio(len(semantic), len(elements), None),
        avu=_ratio(len(arbitrary), len(tokens), 0.0),
        isr=_ratio(len(inline), len(elements), 0.0),
        ccr=_ratio(len(reused), len(usage), None),
        counts=counts,
    )
