"""Auxiliares de easy_pomodoro: congelar o relógio, achar o visor/botão/inputs e ler o rodapé."""

from playwright.sync_api import Locator, Page

from oracles.common.colors import RGB, hue_bucket, to_rgb, with_rgba
from oracles.common.geometry import Box, box
from oracles.common.locators import (
    config_inputs,
    find_play_button,
    find_text,
    minutes_from_value,
    text_of,
    timer_display,
    wait_display,
)
from specui.oracle import Checks

PAUSE_AT = "2026-03-10T10:01:00"  # depois do relógio ter arrancado em 10:00; nenhum timer do app deve existir ainda
MODES = ("Foco Total", "Pausa Curta", "Pausa Longa")


def freeze(page: Page) -> None:
    """Congela o relógio: a partir daqui o tempo só passa com `Checks.advance` (determinístico)."""
    page.clock.pause_at(PAUSE_AT)


def locate(page: Page) -> tuple[Locator | None, Locator | None]:
    """(visor, botão play/pause), com o relógio congelado."""
    freeze(page)
    display = timer_display(page)
    return display, find_play_button(page, display)


def display_text(page: Page) -> str:
    """Texto atual do visor (re-localizado a cada leitura)."""
    return text_of(timer_display(page))


def shows(page: Page, expected: str, timeout_ms: int = 800) -> bool:
    """O visor passa a mostrar `expected` dentro do prazo (False em vez de exceção: serve de pré-condição)."""
    try:
        wait_display(page, expected, timeout_ms)
    except AssertionError:
        return False
    return True


def seconds(text: str) -> int | None:
    parts = text.strip().split(":")
    if len(parts) == 2 and all(p.isdigit() for p in parts):
        return int(parts[0]) * 60 + int(parts[1])
    return None


def input_minutes(field: Locator) -> float | None:
    try:
        return minutes_from_value(field.input_value(timeout=1500))
    except Exception:  # noqa: BLE001
        return None


def type_minutes(field: Locator, minutes: int) -> bool:
    """Digita `minutes` no formato que o input já exibe ('25' ou '25:00', PD-E1) e confirma."""
    try:
        current = field.input_value(timeout=1500)
        field.fill(f"{minutes:02d}:00" if ":" in current else str(minutes))
        field.evaluate("(n) => { n.dispatchEvent(new Event('change', { bubbles: true })); n.blur(); }")
        return True
    except Exception:  # noqa: BLE001
        return False


def click(t: Checks, name: str, target: Locator | None) -> bool:
    return t.act(name, lambda: target.click(timeout=2000)) if target is not None else t.ok(name, False, "controle não encontrado")


_ROUND_ANCESTOR_JS = """
(el) => {
  for (let n = el; n && n !== document.body; n = n.parentElement) {
    const cs = getComputedStyle(n), r = n.getBoundingClientRect();
    const width = parseFloat(cs.borderTopWidth) || 0, radius = parseFloat(cs.borderTopLeftRadius) || 0;
    const round = cs.borderTopLeftRadius.includes('%') ? radius >= 40 : radius >= 0.4 * Math.min(r.width, r.height);
    if (width > 0 && round && r.width > 100) return [r.x, r.y, r.width, r.height];
  }
  return null;
}
"""


def circle_box(display: Locator | None) -> Box | None:
    """Caixa do círculo (primeiro ancestral redondo com borda do visor)."""
    if display is None:
        return None
    try:
        raw = display.evaluate(_ROUND_ANCESTOR_JS, timeout=1500)
    except Exception:  # noqa: BLE001
        return None
    return Box(*raw) if raw else None


def period_name(page: Page, display: Locator | None) -> Locator | None:
    """O nome do período: o 'Foco Total' ACIMA do visor (o do rodapé fica abaixo dele)."""
    db = box(display)
    for text in _all_visible(page, "Foco Total|Pausa Curta|Pausa Longa"):
        b = box(text)
        if db and b and b.cy < db.cy:
            return text
    return None


def footer_label(page: Page, display: Locator | None, mode: str) -> Locator | None:
    """O rótulo do modo no rodapé (ABAIXO do visor)."""
    db = box(display)
    for text in _all_visible(page, mode):
        b = box(text)
        if db and b and b.cy > db.cy:
            return text
    return None


def _all_visible(page: Page, pattern: str) -> list[Locator]:
    import re

    from oracles.common.geometry import visible_all

    return visible_all(page.get_by_text(re.compile(rf"^\s*(?:{pattern})\s*:?\s*$", re.IGNORECASE)))


_LINES_JS = with_rgba(r"""
(minY) => {
  /*RGBA*/
  const found = [];
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (r.width < 500 || r.bottom < minY) continue;
    const cs = getComputedStyle(el);
    const bg = toRGBA(cs.backgroundColor), top = toRGBA(cs.borderTopColor), bottom = toRGBA(cs.borderBottomColor);
    if (r.height <= 4 && alphaOf(bg) > 0.05) found.push([r.top, bg]);
    if (parseFloat(cs.borderTopWidth) > 0 && cs.borderTopStyle !== 'none' && alphaOf(top) > 0.05) found.push([r.top, top]);
    if (parseFloat(cs.borderBottomWidth) > 0 && cs.borderBottomStyle !== 'none' && alphaOf(bottom) > 0.05) found.push([r.bottom, bottom]);
  }
  return found;
}
""")


def divider_lines(page: Page, below_y: float) -> list[tuple[float, RGB | None]]:
    """Linhas horizontais largas (div fina ou borda) abaixo de `below_y`: [(y, cor)]."""
    try:
        return [(y, to_rgb(color)) for y, color in page.evaluate(_LINES_JS, below_y)]
    except Exception:  # noqa: BLE001
        return []


def is_grayish(rgb: RGB | None) -> bool:
    return rgb is not None and hue_bucket(rgb) == "gray" and sum(rgb) / 3 < 235


def read_inputs(page: Page, display: Locator | None) -> list[Locator]:
    return config_inputs(page, display)


def has_text(page: Page, pattern: str) -> bool:
    return find_text(page, pattern) is not None
