"""Auxiliares de hard_kanban: criar cards pelo +/check (PD-H1), arrastar (PD-H3) e achar colunas (PD-H4)."""

import contextlib
import re

from playwright.sync_api import Locator, Page

from oracles.common.colors import RGB, hue_bucket
from oracles.common.dnd import DndDriver
from oracles.common.geometry import Box, box, first_visible, visible_all
from oracles.common.locators import (
    COLUMN_TITLES,
    background_at,
    card_column,
    card_container,
    card_text,
    column_ranges,
    column_title_boxes,
    dashed_boxes,
    find_text,
    plus_candidates,
    row_actions,
)
from oracles.common.probes import filled_rect
from specui.oracle import Checks

_CHECK_NAME = re.compile(r"check|confirm|salv|ok\b|criar|adicion|conclu", re.IGNORECASE)
_CANCEL_NAME = re.compile(r"cancel|descart|fechar|close|\bx\b", re.IGNORECASE)


def ranges(page: Page) -> list[tuple[float, float]] | None:
    return column_ranges(page)


def title_boxes(page: Page) -> list[Box | None]:
    return column_title_boxes(page)


def column_rect(page: Page, index: int):
    """(caixa, cor) do cabeçalho da coluna `index`: o retângulo preenchido do título."""
    return filled_rect(find_text(page, re.escape(COLUMN_TITLES[index]), exact=True))


def body_color(page: Page, index: int) -> RGB | None:
    """Cor do corpo da coluna: uma amostra na margem esquerda, logo abaixo do cabeçalho (fora dos cards)."""
    rect = column_rect(page, index)
    return background_at(page, rect[0].x + 3, rect[0].y1 + 40) if rect else None


_SCROLL_DASHED_JS = """
([lo, hi]) => {
  const els = Array.from(document.querySelectorAll('*')).filter((el) => {
    const cs = getComputedStyle(el), r = el.getBoundingClientRect(), cx = r.x + r.width / 2;
    return cs.borderTopStyle === 'dashed' && parseFloat(cs.borderTopWidth) > 0 && r.width > 80 && r.height > 60 && cx >= lo && cx < hi;
  });
  els.sort((a, b) => b.getBoundingClientRect().y - a.getBoundingClientRect().y);
  if (els.length) els[0].scrollIntoView({ block: 'nearest' });
  return els.length > 0;
}
"""


def placeholder(page: Page, col_ranges: list[tuple[float, float]], index: int = 0) -> Box | None:
    """O card esmaecido (borda dashed) da coluna `index`; o mais baixo, se houver mais de um.

    Ele fica "no final da coluna" e pode estar abaixo da área visível: rola até ele antes de medir, senão o clique e
    a leitura de opacidade caem fora da tela."""
    lo, hi = col_ranges[index]
    with contextlib.suppress(Exception):
        page.evaluate(_SCROLL_DASHED_JS, [max(lo, -1e9), min(hi, 1e9)])
    found = [b for b in dashed_boxes(page) if lo <= b.cx < hi]
    return max(found, key=lambda b: b.y) if found else None


def input_in_column(page: Page, col_ranges: list[tuple[float, float]], index: int = 0) -> Locator | None:
    lo, hi = col_ranges[index]
    fields = [f for f in visible_all(page.get_by_role("textbox")) if (b := box(f)) and lo <= b.cx < hi]
    return fields[-1] if fields else None


def start_creation(page: Page) -> Locator | None:
    """Clica no + do card esmaecido e devolve o input que surge (None se nada aparecer)."""
    col_ranges = ranges(page)
    if col_ranges is None:
        return None
    target = placeholder(page, col_ranges)
    try:
        if target is not None:
            page.mouse.click(target.cx, target.cy)
        else:
            plus = next((p for p in plus_candidates(page) if (b := box(p)) and col_ranges[0][0] <= b.cx < col_ranges[0][1]), None)
            if plus is None:
                return None
            plus.click(timeout=2000)
    except Exception:  # noqa: BLE001
        return None
    page.wait_for_timeout(500)  # animação de transição
    return input_in_column(page, col_ranges)


def check_and_cancel(field: Locator) -> tuple[Locator | None, Locator | None]:
    """Ícones de confirmar (check) e cancelar (X) do card que contém `field`: pelo nome, senão pela posição
    (o prompt: no canto superior direito do card, check e X, nessa ordem)."""
    container = card_container(field)
    if not container.count():
        return None, None
    check = first_visible(container.get_by_role("button", name=_CHECK_NAME))
    cancel = first_visible(container.get_by_role("button", name=_CANCEL_NAME))
    if check is not None and cancel is not None:
        return check, cancel
    positional = row_actions(container)
    return check or positional["edit"], cancel or positional["delete"]


def create_card(page: Page, description: str) -> bool:
    field = start_creation(page)
    if field is None:
        return False
    try:
        field.fill(description)
        check, _cancel = check_and_cancel(field)
        if check is None:
            return False
        check.click(timeout=2000)
    except Exception:  # noqa: BLE001
        return False
    page.wait_for_timeout(500)
    return card_text(page, description) is not None


def need_cards(page: Page, t: Checks, descriptions: list[str]) -> None:
    """Pré-condição: cria os cards pela UI; se algum não aparecer, o caso fica bloqueado (NO)."""
    for description in descriptions:
        t.require(f"criar o card '{description}' pelo + e pelo check", create_card(page, description), "o card não apareceu")


def card_box(page: Page, description: str) -> Box | None:
    return box(card_text(page, description))


def column_index(page: Page, col_ranges: list[tuple[float, float]], description: str) -> int | None:
    return card_column(page, col_ranges, description)


def column_center(page: Page, index: int) -> float | None:
    b = title_boxes(page)[index]
    return b.cx if b else None


def drag_target(page: Page, index: int) -> tuple[float, float] | None:
    """Ponto de soltura: centro da coluna, 170 px abaixo do cabeçalho (região onde ficam os cards), mantido DENTRO da
    área visível (o mouse não alcança fora da tela, e a página pode ter rolado)."""
    b = title_boxes(page)[index]
    if b is None:
        return None
    height = (page.viewport_size or {"height": 900})["height"]
    return b.cx, min(max(b.y1 + 170, 100.0), height - 40.0)


def bring_into_view(locator: Locator | None) -> None:
    """Rola até o card (cards grandes ficam abaixo da área visível; o mouse só arrasta o que está na tela)."""
    if locator is not None:
        with contextlib.suppress(Exception):
            card_container(locator).first.scroll_into_view_if_needed(timeout=1500)


def move_to_column(page: Page, driver: DndDriver, description: str, col_ranges, index: int, expect_move: bool = True) -> bool:
    """Arrasta o card para a coluna `index`. Com `expect_move`, tenta cada estratégia até o card mudar de coluna
    (e devolve se mudou); sem ele, faz um único arrasto com a estratégia já validada e devolve se o card chegou lá."""
    bring_into_view(card_text(page, description))
    src, to = card_text(page, description), drag_target(page, index)
    if src is None or to is None:
        return False
    if expect_move:
        return driver.move_until(src, to, lambda: column_index(page, col_ranges, description) == index)
    driver.drag(src, to)
    return column_index(page, col_ranges, description) == index


def is_off_white(rgb: RGB | None) -> bool:
    """Off-white: claro e pouco saturado (o prompt não dá o hex; a spec dá #D7CFCF, nível B)."""
    return rgb is not None and min(rgb) >= 185 and hue_bucket(rgb, 0.2) == "gray"
