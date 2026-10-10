"""Sondas genéricas de página compartilhadas pelas suítes: retângulo preenchido, linhas horizontais e cores claras."""

from playwright.sync_api import Locator, Page

from oracles.common.colors import RGB, to_rgb, with_rgba
from oracles.common.geometry import Box, visible_all

_RECT_JS = with_rgba(r"""
(el) => {
  /*RGBA*/
  for (let n = el, i = 0; n && i < 4; n = n.parentElement, i++) {
    const bg = toRGBA(getComputedStyle(n).backgroundColor);
    if (alphaOf(bg) > 0.5) { const r = n.getBoundingClientRect(); return [r.x, r.y, r.width, r.height, bg]; }
  }
  return null;
}
""")


def filled_rect(locator: Locator | None) -> tuple[Box, RGB] | None:
    """O retângulo preenchido (o próprio elemento ou o ancestral mais próximo com fundo opaco) e sua cor."""
    if locator is None:
        return None
    try:
        raw = locator.evaluate(_RECT_JS, timeout=1500)
    except Exception:  # noqa: BLE001
        return None
    if not raw:
        return None
    color = to_rgb(raw[4])
    return (Box(*raw[:4]), color) if color else None


_LINES_JS = with_rgba(r"""
() => {
  /*RGBA*/
  const found = [];
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (r.width < 300) continue;
    const cs = getComputedStyle(el);
    const bg = toRGBA(cs.backgroundColor), top = toRGBA(cs.borderTopColor), bottom = toRGBA(cs.borderBottomColor);
    if (r.height <= 4 && r.height > 0 && alphaOf(bg) > 0.05) found.push([r.x, r.top, r.width, bg]);
    if (parseFloat(cs.borderTopWidth) > 0 && cs.borderTopStyle !== 'none' && alphaOf(top) > 0.05) found.push([r.x, r.top, r.width, top]);
    if (parseFloat(cs.borderBottomWidth) > 0 && cs.borderBottomStyle !== 'none' && alphaOf(bottom) > 0.05) found.push([r.x, r.bottom, r.width, bottom]);
  }
  return found;
}
""")


def horizontal_lines(page: Page) -> list[tuple[float, float, float, RGB | None]]:
    """Linhas horizontais largas (div fina ou borda): [(x, y, largura, cor)]."""
    try:
        return [(x, y, w, to_rgb(color)) for x, y, w, color in page.evaluate(_LINES_JS)]
    except Exception:  # noqa: BLE001
        return []


def is_light(rgb: RGB | None, minimum: int = 225) -> bool:
    return rgb is not None and min(rgb) >= minimum


def _value_of(field: Locator) -> str | None:
    try:
        return field.input_value(timeout=500)
    except Exception:  # noqa: BLE001
        return None


def field_with_value(page: Page, value: str) -> Locator | None:
    """O campo de texto visível cujo valor atual é `value` (a linha em edição)."""
    return next((f for f in visible_all(page.get_by_role("textbox")) if _value_of(f) == value), None)
