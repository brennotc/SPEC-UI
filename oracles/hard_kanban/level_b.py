"""Nível B de hard_kanban: exigências que só a `## Specification` faz (hex, medidas, edição inline, ARIA, semântica)."""

import re

from playwright.sync_api import Page

from oracles.common.colors import (
    RGB,
    computed,
    delta_e,
    effective_background,
    text_color,
    with_rgba,
)
from oracles.common.geometry import box, first_visible
from oracles.common.locators import (
    COLUMN_TITLES,
    background_at,
    card_actions,
    card_container,
    card_text,
    find_text,
    icon_color,
    icon_on_same_row,
)
from oracles.common.probes import field_with_value, filled_rect
from oracles.hard_kanban.helpers import (
    body_color,
    check_and_cancel,
    column_rect,
    need_cards,
    placeholder,
    ranges,
    start_creation,
    title_boxes,
)
from specui.oracle import Checks, case

TOL = 5.0
HEADERS = [(0x0B, 0x73, 0xB7), (0xB7, 0x7A, 0x0B), (0x44, 0x0B, 0xB7), (0x10, 0x56, 0x10)]
BODIES = [(0x9F, 0xBA, 0xCC), (0xCC, 0xB5, 0x9F), (0xAA, 0x9F, 0xCC), (0xC5, 0xCC, 0x9F)]
GREEN_HEADER, RED, GRAY, CARD = (0x10, 0x56, 0x10), (0xB5, 0x00, 0x00), (0x65, 0x60, 0x60), (0xD7, 0xCF, 0xCF)


def _near(actual: RGB | None, expected: RGB, tolerance: float = TOL) -> bool:
    return actual is not None and delta_e(actual, expected) <= tolerance


def _within(value: float | None, target: float, tolerance: float = 2.0) -> bool:
    return value is not None and abs(value - target) <= tolerance


def _px(value: str | None) -> float | None:
    m = re.match(r"-?[\d.]+", value or "")
    return float(m.group()) if m else None


def _opacity_at(page: Page, b) -> float:
    return float(page.evaluate(
        "([x, y]) => { let o = 1; for (let n = document.elementFromPoint(x, y); n && n !== document.documentElement; n = n.parentElement) "
        "o *= parseFloat(getComputedStyle(n).opacity); return o; }", [b.cx, b.cy]))


@case("H-B-01", requirements=["H-S01"], level="B",
      task="Medir o header e o fundo geral.",
      expected="70 px, #105610, ícone e texto brancos; fundo geral #D7CFCF.")
def header_spec(page: Page, t: Checks) -> None:
    header = page.locator("header").first
    t.require("existe um <header>", header.count() > 0 and header.is_visible())
    hb = box(header)
    t.ok("altura de 70 px", _within(hb.h if hb else None, 70), f"{hb}")
    bg = filled_rect(header)
    t.ok("fundo #105610 (ΔE ≤ 5)", bool(bg and _near(bg[1], GREEN_HEADER)), f"{bg[1] if bg else None}")
    title = find_text(page, "kanban", exact=True)
    ink = text_color(title)
    t.ok("texto 'Kanban' branco", ink is not None and min(ink) >= 240, f"{ink}")
    icon = icon_on_same_row(page, title)
    icon_ink = icon_color(icon) if icon is not None else None
    t.ok("ícone de lista branco", icon_ink is not None and min(icon_ink) >= 240, f"{icon_ink}")
    samples = [background_at(page, x, y) for x, y in ((2, 450), (1437, 450), (720, 897))] + [effective_background(page.locator("body"))]
    t.ok("fundo geral #D7CFCF (ΔE ≤ 5)", any(_near(s, CARD) for s in samples), f"{samples}")


@case("H-B-02", requirements=["H-S02"], level="B",
      task="Medir o cabeçalho e o corpo de cada coluna.",
      expected="Cores exatas do mapeamento e largura mínima de 340 px.")
def columns_spec(page: Page, t: Checks) -> None:
    for index, title in enumerate(COLUMN_TITLES):
        rect = column_rect(page, index)
        t.ok(f"'{title}': cabeçalho com a cor forte do mapeamento", bool(rect and _near(rect[1], HEADERS[index])), f"{rect[1] if rect else None}")
        t.ok(f"'{title}': largura ≥ 340 px", bool(rect and rect[0].w >= 338), f"{rect[0].w if rect else None}")
        body = body_color(page, index)
        t.ok(f"'{title}': corpo com a cor fraca do mapeamento", _near(body, BODIES[index], 6.0), f"{body}")


@case("H-B-03", requirements=["H-S03"], level="B",
      task="Medir o card de criação em repouso.",
      expected="Opacidade 70 %, borda dashed #656060 e + cinza.")
def placeholder_spec(page: Page, t: Checks) -> None:
    col_ranges = ranges(page)
    t.require("as quatro colunas existem", col_ranges is not None)
    ph = placeholder(page, col_ranges)
    t.require("existe o card esmaecido", ph is not None)
    t.ok("opacidade de 70 %", abs(_opacity_at(page, ph) - 0.7) <= 0.05, f"{_opacity_at(page, ph)}")
    border = page.evaluate(with_rgba(
        "([x, y]) => { /*RGBA*/ for (let n = document.elementFromPoint(x, y); n; n = n.parentElement) { const cs = getComputedStyle(n);"
        " if (cs.borderTopStyle === 'dashed') return [toRGBA(cs.borderTopColor), cs.borderTopStyle]; } return null; }"), [ph.cx, ph.cy + 0])
    from oracles.common.colors import to_rgb

    t.ok("borda dashed", bool(border) and border[1] == "dashed")
    t.ok("cor da borda #656060 (ΔE ≤ 8)", bool(border) and _near(to_rgb(border[0]), GRAY, 8.0), f"{border}")
    plus = first_visible(page.get_by_role("button", name=re.compile(r"adicion|add|nov[ao]|criar|\+", re.IGNORECASE))) \
        or first_visible(page.get_by_text("+", exact=True))
    t.ok("o + é cinza", plus is not None and _near(icon_color(plus), GRAY, 12.0), f"{icon_color(plus) if plus else None}")


@case("H-B-04", requirements=["H-S04"], level="B",
      task="Criar um card e medi-lo.",
      expected="274×191 px, fundo #D7CFCF, descrição preta 24 px centralizada, lixeira #B50000.")
def card_spec(page: Page, t: Checks) -> None:
    need_cards(page, t, ["Medidas"])
    text = card_text(page, "Medidas")
    container = card_container(text)
    cb, tb = box(container), box(text)
    t.require("o card tem um contêiner", cb is not None)
    t.ok("274 × 191 px", _within(cb.w, 274, 3) and _within(cb.h, 191, 3), f"{cb}")
    t.ok("fundo #D7CFCF (ΔE ≤ 5)", _near(effective_background(container), CARD), f"{effective_background(container)}")
    t.ok("descrição a 24 px", _within(_px(computed(text, "font-size")), 24, 1))
    t.ok("descrição preta", (ink := text_color(text)) is not None and max(ink) <= 40, f"{text_color(text)}")
    t.ok("descrição centralizada", bool(tb and abs(tb.cx - cb.cx) <= 0.08 * cb.w))
    actions = card_actions(page, "Medidas")
    t.ok("lixeira #B50000 (ΔE ≤ 5)", _near(icon_color(actions["delete"]) if actions["delete"] else None, RED), f"{icon_color(actions['delete']) if actions['delete'] else None}")


@case("H-B-05", requirements=["H-S05"], level="B",
      task="Clicar no + e inspecionar o modo de criação.",
      expected="Input com aria-label 'Descrição da nova tarefa', check #105610 e X #B50000.")
def creation_spec(page: Page, t: Checks) -> None:
    field = start_creation(page)
    t.require("o modo de criação abre", field is not None)
    t.ok("aria-label do input 'Descrição da nova tarefa'", field.get_attribute("aria-label") == "Descrição da nova tarefa", str(field.get_attribute("aria-label")))
    check, cancel = check_and_cancel(field)
    t.ok("check na cor verde do header (ΔE ≤ 5)", _near(icon_color(check) if check else None, GREEN_HEADER), f"{icon_color(check) if check else None}")
    t.ok("X em #B50000 (ΔE ≤ 5)", _near(icon_color(cancel) if cancel else None, RED), f"{icon_color(cancel) if cancel else None}")


@case("H-B-06", requirements=["H-S06"], level="B",
      task="Criar dois cards e olhar o card esmaecido.",
      expected="O novo card é o último e o card de criação volta a 70 % de opacidade.")
def new_card_last(page: Page, t: Checks) -> None:
    need_cards(page, t, ["Primeiro", "Ultimo"])
    ph = placeholder(page, ranges(page))  # rola primeiro: as caixas abaixo ficam no mesmo referencial
    first, last = box(card_text(page, "Primeiro")), box(card_text(page, "Ultimo"))
    t.ok("o novo card é o último da lista", bool(first and last and first.cy < last.cy))
    t.ok("o card de criação volta abaixo dele", bool(ph and last and ph.cy > last.cy))
    t.ok("o card de criação volta a 70 % de opacidade", bool(ph) and abs(_opacity_at(page, ph) - 0.7) <= 0.05, f"{_opacity_at(page, ph) if ph else None}")


@case("H-B-07", requirements=["H-S07"], level="B",
      task="Editar um card com o lápis: salvar com o check e descartar com o X.",
      expected="O texto vira input com check e X; check atualiza a descrição, X a mantém.")
def edit_spec(page: Page, t: Checks) -> None:
    need_cards(page, t, ["Original"])
    actions = card_actions(page, "Original")
    t.require("o card tem lápis", actions["edit"] is not None)
    t.act("clicar no lápis", lambda: actions["edit"].click(timeout=2000))
    page.wait_for_timeout(300)
    field = field_with_value(page, "Original")
    t.require("a descrição vira um input editável", field is not None)
    check, cancel = check_and_cancel(field)
    t.ok("aparecem o check e o X", check is not None and cancel is not None)
    t.act("alterar o texto", lambda: field.fill("Editado"))
    t.act("clicar no check", lambda: check.click(timeout=2000))
    page.wait_for_timeout(300)
    t.ok("a descrição foi atualizada", card_text(page, "Editado") is not None)
    again = card_actions(page, "Editado")
    t.require("o card voltou a ter lápis", again["edit"] is not None)
    t.act("clicar no lápis de novo", lambda: again["edit"].click(timeout=2000))
    page.wait_for_timeout(300)
    field = field_with_value(page, "Editado")
    t.require("o input aparece de novo", field is not None)
    _check, cancel = check_and_cancel(field)
    t.act("alterar o texto", lambda: field.fill("Descartado"))
    t.act("clicar no X", lambda: cancel.click(timeout=2000))
    page.wait_for_timeout(300)
    t.ok("a edição foi descartada e a descrição original mantida", card_text(page, "Editado") is not None and card_text(page, "Descartado") is None)


@case("H-B-08", requirements=["H-S08"], level="B",
      task="Inspecionar a estrutura da página.",
      expected="<header>, <main>, quatro <section> (uma por coluna) e um <article> por card.")
def semantics(page: Page, t: Checks) -> None:
    need_cards(page, t, ["Semantica A", "Semantica B"])
    t.ok("existe <header>", page.locator("header").count() >= 1)
    t.ok("existe <main>", page.locator("main").count() >= 1)
    t.ok("há quatro <section> (colunas)", page.locator("section").count() >= 4, f"{page.locator('section').count()}")
    t.ok("há um <article> por card", page.locator("article").count() >= 2, f"{page.locator('article').count()}")


@case("H-B-09", requirements=["H-S09"], level="B",
      task="Inspecionar os nomes acessíveis dos botões de ícone.",
      expected="Lápis, lixeira, +, check e X têm aria-label descritivo.")
def aria_labels(page: Page, t: Checks) -> None:
    need_cards(page, t, ["Aria"])
    container = card_container(card_text(page, "Aria"))
    t.ok("lápis com nome acessível", first_visible(container.get_by_role("button", name=re.compile(r"edit", re.IGNORECASE))) is not None)
    t.ok("lixeira com nome acessível", first_visible(container.get_by_role("button", name=re.compile(r"exclu|delet|remov", re.IGNORECASE))) is not None)
    t.ok("+ com nome acessível", first_visible(page.get_by_role("button", name=re.compile(r"adicion|add|nov[ao]|criar", re.IGNORECASE))) is not None)
    field = start_creation(page)
    t.require("o modo de criação abre", field is not None)
    box_container = card_container(field)
    t.ok("check com nome acessível", first_visible(box_container.get_by_role("button", name=re.compile(r"confirm|salv|check|criar|adicion", re.IGNORECASE))) is not None)
    t.ok("X com nome acessível", first_visible(box_container.get_by_role("button", name=re.compile(r"cancel|descart|fechar|close", re.IGNORECASE))) is not None)


@case("H-B-10", requirements=["H-S10"], level="B",
      task="Navegar por Tab pelo quadro.",
      expected="Botões, o card de criação e os campos mostram anel de foco.")
def focus_rings(page: Page, t: Checks) -> None:
    need_cards(page, t, ["Foco"])
    page.mouse.click(5, 5)
    rings: dict[str, list[bool]] = {}
    for _ in range(30):
        page.keyboard.press("Tab")
        info = page.evaluate(
            "() => { const n = document.activeElement; if (!n || n === document.body) return null; const cs = getComputedStyle(n);"
            " const kind = n.tagName === 'INPUT' ? 'input' : (n.tagName === 'BUTTON' || n.getAttribute('role') === 'button' ? 'button' : n.tagName.toLowerCase());"
            " const ring = (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0) || (cs.boxShadow && cs.boxShadow !== 'none');"
            " return [kind, !!ring]; }"
        )
        if info:
            rings.setdefault(info[0], []).append(info[1])
    t.require("a navegação por Tab alcança controles", bool(rings))
    for kind in ("button", "input"):
        if kind in rings:
            t.ok(f"controles do tipo '{kind}' mostram anel de foco", all(rings[kind]), f"{rings[kind]}")
    t.ok("o título das colunas continua visível", all(title_boxes(page)))
