"""Métricas do Figma2Code com snapshots sintéticos de valores conhecidos."""

import pytest

from specui.metrics.code_quality import (
    class_names,
    classify_length,
    compute_code_quality,
    covered_bands,
    media_boundaries,
    parse_declarations,
    resolve_vars,
)


def el(tag, classes=(), position="static", display="block", child_count=0, inline=False, in_svg=False):
    return {"tag": tag, "classes": list(classes), "inline_style": inline, "position": position,
            "display": display, "child_count": child_count, "in_svg": in_svg}


def rule(selector, css, layer=None, origin="global", media=None):
    return {"selector": selector, "css_text": css, "layer": layer, "origin": origin, "media": media, "nested": False}


ROOT = el("app-root", child_count=1)
THEME = rule(":root, :host", "--spacing: .25rem; --container-md: 28rem;", layer="theme")


def snap(elements, rules=()):
    return {"elements": [ROOT, *elements], "rules": [THEME, *rules]}


def cq(elements, rules=()):
    return compute_code_quality(snap(elements, rules))


# ---------------------------------------------------------------- razões sobre o DOM


def test_apr_counts_absolute_and_fixed_among_positioned():
    elements = [el("div", position="relative")] * 7 + [el("div", position="absolute")] * 2 + [el("div", position="fixed")]
    elements += [el("div")] * 5  # static não entra no denominador
    m = cq(elements)
    assert m.apr == pytest.approx(0.3)
    assert m.counts["positioned_absolute"] == 3 and m.counts["positioned_total"] == 10


def test_apr_is_zero_when_nothing_is_positioned():
    assert cq([el("div")] * 3).apr == 0.0


def test_fu_is_flex_or_grid_among_containers():
    elements = [el("div", display="flex", child_count=2), el("div", display="grid", child_count=1),
                el("div", display="inline-flex", child_count=3), el("div", display="block", child_count=2),
                el("span", display="flex", child_count=0)]  # folha: não é container
    m = cq(elements)
    assert m.fu == pytest.approx(0.75)
    assert m.counts["containers_flex_grid"] == 3 and m.counts["containers_total"] == 4
    assert cq([el("div")]).fu is None  # sem containers: não há o que medir


def test_str_semantic_elements_over_all():
    m = cq([el("header"), el("main"), el("section"), el("div"), el("div"), el("span")])
    assert m.str_ == pytest.approx(0.5)
    assert m.counts["semantic_elements"] == 3 and m.counts["elements_total"] == 6


def test_avu_counts_arbitrary_values_and_ignores_angular_classes():
    m = cq([el("div", ["w-[503px]", "bg-[#ff0]", "p-4", "flex", "ng-star-inserted", "cdk-overlay-pane"])])
    assert m.avu == pytest.approx(0.5)
    assert m.counts["arbitrary_classes"] == 2 and m.counts["classes_total"] == 4
    assert cq([el("div")]).avu == 0.0  # sem classes: nada a penalizar


def test_isr_inline_styles():
    m = cq([el("div", inline=True), el("div", inline=True)] + [el("div")] * 6)
    assert m.isr == pytest.approx(0.25) and m.counts["inline_style_elements"] == 2


def test_scope_excludes_app_root_and_svg():
    elements = [el("div", ["a"]), el("svg", child_count=2), el("path", in_svg=True, inline=True),
                el("g", in_svg=True, position="absolute")]
    m = cq(elements)
    assert m.counts["elements_total"] == 1  # só o div: sem app-root, sem svg e descendentes
    assert m.isr == 0.0 and m.apr == 0.0


def test_empty_snapshot_is_an_error():
    with pytest.raises(ValueError, match="sem elementos"):
        compute_code_quality({"elements": [], "rules": []})


# ---------------------------------------------------------------- RUR (unidades de layout)


def test_rur_relative_vs_absolute_layout_declarations():
    rules = [
        rule(".p-4", "padding: calc(var(--spacing) * 4);", "utilities"),  # relativo (rem via tema)
        rule(".w-\\[503px\\]", "width: 503px;", "utilities"),  # absoluto
        rule(".w-full", "width: 100%;", "utilities"),  # relativo
        rule(".mx-auto", "margin-inline: auto;", "utilities"),  # palavra-chave: não conta
        rule(".max-w-md", "max-width: var(--container-md);", "utilities"),  # relativo (28rem)
        rule("*", "margin: 0; padding: 0; width: 10px;", "base"),  # preflight: fora
        rule(".card[_ngcontent-x]", "padding: 10px; margin: 1rem 2px; width: 50%; color: red; font-size: 16px;",
             origin="component"),
    ]
    m = cq([el("div")], rules)
    # relativos: p-4, w-full, max-w-md, 1rem, 50%  | absolutos: 503px, 10px, 2px
    assert m.counts["layout_declarations_relative"] == 5 and m.counts["layout_declarations_total"] == 8
    assert m.rur == pytest.approx(5 / 8)


def test_rur_is_none_without_layout_declarations():
    assert cq([el("div")], [rule(".x", "color: red;", "utilities")]).rur is None


@pytest.mark.parametrize(
    "value, expected",
    [
        ("100%", (1, 0)), ("12px", (0, 1)), ("auto", (0, 0)), ("0", (0, 0)), ("0px", (0, 0)),
        ("0px 12px", (0, 1)), ("1rem 2px", (1, 1)), ("calc(.25rem * 4)", (1, 0)),
        ("calc(100% - 20px)", (1, 0)),  # token com qualquer unidade relativa conta como relativo
        ("repeat(2, minmax(0px, 1fr))", (1, 0)), ("200px 1fr 1fr", (2, 1)), ("min-content", (0, 0)),
        ("100vh", (1, 0)), ("fit-content(300px)", (0, 1)),
    ],
)
def test_classify_length(value, expected):
    assert classify_length(value) == expected


def test_classify_length_resolves_theme_variables():
    variables = {"--spacing": ".25rem", "--w": "var(--spacing)"}
    assert classify_length("calc(var(--spacing) * 4)", variables) == (1, 0)
    assert classify_length("var(--w)", variables) == (1, 0)
    assert classify_length("var(--missing, 10px)", variables) == (0, 1)  # fallback
    assert classify_length("var(--missing)", variables) == (0, 0)  # sem valor: ignora


def test_resolve_vars_bounded():
    assert resolve_vars("var(--a)", {"--a": "var(--b)", "--b": "7px"}) == "7px"
    assert resolve_vars("var(--loop)", {"--loop": "var(--loop)"}) is not None  # não trava


def test_parse_declarations():
    css = "width: 10px; background: url('a;b.png'); margin: calc(1px + 2px) ; color: red !important;;"
    assert parse_declarations(css) == [
        ("width", "10px"), ("background", "url('a;b.png')"), ("margin", "calc(1px + 2px)"), ("color", "red"),
    ]
    assert parse_declarations("") == []


def test_class_names_unescape_tailwind_selectors():
    assert class_names(".w-\\[123px\\]") == {"w-[123px]"}
    assert class_names(".md\\:p-8:hover, .btn[_ngcontent-ng-c1] > .icon") == {"md:p-8", "btn", "icon"}
    assert class_names("") == set()


# ---------------------------------------------------------------- BC (faixas de viewport)


@pytest.mark.parametrize(
    "media, expected",
    [
        ("(min-width: 48rem)", [768.0]),
        ("(min-width: 640px)", [640.0]),
        ("(max-width: 599px)", [599.0]),
        ("(width >= 40rem)", [640.0]),
        ("(40rem <= width < 64rem)", [640.0, 1024.0]),
        ("(min-width: 700px) and (hover: hover)", [700.0]),
        ("not (min-width: 40rem)", [639.99]),  # max-sm: mira abaixo do limite
        ("(min-height: 500px)", []),
        ("(prefers-color-scheme: dark)", []),
        (None, []),
    ],
)
def test_media_boundaries(media, expected):
    assert media_boundaries(media) == pytest.approx(expected)


def test_covered_bands():
    assert covered_bands([639.99]) == {"S"}
    assert covered_bands([768, 1024, 1280]) == {"M", "L", "XL"}
    assert covered_bands([640]) == {"M"} and covered_bands([1536]) == {"XL"}
    assert covered_bands([0, 5000]) == {"XL"}  # 0 não está estritamente dentro de S
    assert covered_bands([]) == set()


def test_bc_from_rules_and_all_bands():
    medias = ["not (min-width: 40rem)", "(min-width: 48rem)", "(min-width: 64rem)", "(min-width: 80rem)"]
    rules = [rule(f".r{i}", "display: none;", "utilities", media=m) for i, m in enumerate(medias)]
    assert cq([el("div")], rules).bc == 1.0
    assert cq([el("div")], rules[1:2]).bc == 0.25
    assert cq([el("div")], []).bc == 0.0
    # media queries de camadas theme/base não são código do modelo
    base = [rule("x", "a: b;", "base", media="(min-width: 48rem)")]
    assert cq([el("div")], base).bc == 0.0


# ---------------------------------------------------------------- CCR (classes customizadas)


def test_ccr_reused_custom_classes():
    rules = [
        rule(".btn", "padding: 4px;"),  # CSS global do modelo (sem camada)
        rule(".card[_ngcontent-x]", "margin: 1rem;", origin="component"),
        rule(".dead", "color: red;"),  # definida e nunca usada
        rule(".flex", "display: flex;", "utilities"),  # Tailwind: não é customizada
    ]
    elements = [el("div", ["btn", "flex"]), el("div", ["btn", "card"]), el("div", ["mystery"])]
    m = cq(elements, rules)
    assert m.ccr == pytest.approx(0.5)  # btn reutilizada (2x), card só 1x
    assert m.counts["custom_classes_used"] == 2 and m.counts["custom_classes_reused"] == 1
    assert m.counts["custom_classes_dead"] == 1 and m.counts["classes_undefined"] == 1  # mystery


def test_ccr_none_without_custom_classes():
    assert cq([el("div", ["flex", "p-4"])], [rule(".flex", "display: flex;", "utilities")]).ccr is None


def test_metrics_model_aliases_str():
    dumped = cq([el("header")]).model_dump(by_alias=True)
    assert "str" in dumped and "str_" not in dumped
