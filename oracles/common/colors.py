"""Cores: leitura de cores CSS computadas, faixas de matiz, luminância e distância ΔE2000.

Os testes de nível A comparam por FAIXA de matiz ("vermelho", "verde"...), não por hex: o prompt só
diz as cores pelo nome. O hex exato (ΔE2000) é exigência da spec, logo nível B.
"""

import colorsys
import re

from playwright.sync_api import Locator

RGB = tuple[int, int, int]

_RGB_FN = re.compile(r"rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)(?:\s*[,/]\s*([\d.]+%?))?\s*\)")
_SRGB_FN = re.compile(r"color\(srgb\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)(?:\s*/\s*([\d.]+%?))?\s*\)")
_HEX = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

# Faixas de matiz (graus). Vermelho dá a volta no círculo.
HUE_BUCKETS: dict[str, list[tuple[float, float]]] = {
    "red": [(345.0, 360.0), (0.0, 15.0)],
    "orange": [(15.0, 46.0)],
    "yellow": [(46.0, 76.0)],
    "green": [(76.0, 166.0)],
    "blue": [(190.0, 251.0)],
    "purple": [(251.0, 301.0)],
}


def _alpha(raw: str | None) -> float:
    if raw is None:
        return 1.0
    return float(raw[:-1]) / 100 if raw.endswith("%") else float(raw)


def parse_css_color(value: str | None) -> tuple[int, int, int, float] | None:
    """`rgb()`, `rgba()`, `color(srgb ...)` ou `#hex` -> (r, g, b, alpha); None se não entender."""
    if not value:
        return None
    value = value.strip()
    if (m := _RGB_FN.search(value)) is not None:
        r, g, b = (round(float(x)) for x in m.groups()[:3])
        return r, g, b, _alpha(m.group(4))
    if (m := _SRGB_FN.search(value)) is not None:
        r, g, b = (round(float(x) * 255) for x in m.groups()[:3])
        return r, g, b, _alpha(m.group(4))
    if (m := _HEX.match(value)) is not None:
        h = m.group(1)
        h = "".join(c * 2 for c in h) if len(h) == 3 else h
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 1.0
    return None


def to_rgb(value: str | None) -> RGB | None:
    parsed = parse_css_color(value)
    return None if parsed is None else (parsed[0], parsed[1], parsed[2])


def rgb_to_hsl(rgb: RGB) -> tuple[float, float, float]:
    """(matiz 0-360, saturação 0-1, luminosidade 0-1)."""
    h, l, s = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
    return h * 360, s, l


# Decisões do pesquisador após o piloto 1 (ver pending.yaml, PD-C1 e PD-C2):
# PD-C1: um cinza levemente tingido (ex.: cinza-azulado claro, slate) é cinza. A saturação HSL explode em cores muito claras
#        (226,232,240 tem saturação 0,32), então também conta como cinza quem tem croma (máx − mín) de até 6 % da escala.
# PD-C2: perto do limite entre duas faixas de matiz há margem de ±5° (ex.: vermelho-rosado a 344° ainda é vermelho;
#        lilás a 249° ainda é roxo). Cinza nunca vira cor pela margem.
GRAY_MAX_CHROMA = 0.06
HUE_TOLERANCE = 5.0


def hue_bucket(rgb: RGB | None, min_saturation: float = 0.15) -> str | None:
    """'red' | 'orange' | 'yellow' | 'green' | 'blue' | 'purple' | 'gray' | None (ciano/outro)."""
    if rgb is None:
        return None
    hue, sat, light = rgb_to_hsl(rgb)
    chroma = (max(rgb) - min(rgb)) / 255
    if sat < min_saturation or chroma <= GRAY_MAX_CHROMA or light < 0.04 or light > 0.97:
        return "gray"
    for name, ranges in HUE_BUCKETS.items():
        if any(lo <= hue < hi for lo, hi in ranges):
            return name
    return None


def hue_matches(rgb: RGB | None, name: str, tolerance: float = HUE_TOLERANCE) -> bool:
    """A cor é da família `name` ('red', 'green'...), com margem de `tolerance` graus nos limites da faixa (PD-C2)."""
    bucket = hue_bucket(rgb)
    if bucket == name:
        return True
    if rgb is None or bucket == "gray" or name not in HUE_BUCKETS:
        return False
    hue = rgb_to_hsl(rgb)[0]
    return any(lo - tolerance <= h < hi + tolerance for lo, hi in HUE_BUCKETS[name] for h in (hue, hue - 360, hue + 360))


def relative_luminance(rgb: RGB) -> float:
    """Luminância relativa WCAG (0 = preto, 1 = branco)."""
    def lin(c: int) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def is_white(rgb: RGB | None, threshold: float = 0.85) -> bool:
    return rgb is not None and relative_luminance(rgb) >= threshold


def is_dark(rgb: RGB | None, threshold: float = 0.10) -> bool:
    return rgb is not None and relative_luminance(rgb) <= threshold


def delta_e(a: RGB, b: RGB) -> float:
    """Distância CIEDE2000 entre duas cores sRGB."""
    import numpy as np
    from skimage.color import deltaE_ciede2000, rgb2lab

    la = rgb2lab(np.array([[a]], dtype=float) / 255.0)
    lb = rgb2lab(np.array([[b]], dtype=float) / 255.0)
    return float(deltaE_ciede2000(la, lb)[0, 0])


# ----------------------------------------------------------------------------- leitura no navegador

# O Tailwind 4 calcula cores em oklch/oklab: em vez de interpretar cada formato, o navegador PINTA a cor num
# canvas de 1 pixel e devolvemos o pixel como rgba(). Vale para qualquer cor que o Chrome entenda.
RGBA_JS = r"""
  const toRGBA = (c) => {
    if (!c || c === 'none' || c === 'transparent' || c.startsWith('url')) return 'rgba(0, 0, 0, 0)';
    const cv = document.createElement('canvas');
    cv.width = cv.height = 1;
    const x = cv.getContext('2d', { willReadFrequently: true });
    x.fillStyle = 'rgba(0, 0, 0, 0)';
    x.fillStyle = c;
    x.fillRect(0, 0, 1, 1);
    const d = x.getImageData(0, 0, 1, 1).data;
    return `rgba(${d[0]}, ${d[1]}, ${d[2]}, ${(d[3] / 255).toFixed(3)})`;
  };
  const alphaOf = (rgba) => parseFloat(rgba.slice(rgba.lastIndexOf(',') + 1));
"""


def with_rgba(js: str) -> str:
    """Injeta `toRGBA`/`alphaOf` no lugar do marcador `/*RGBA*/` de um script."""
    return js.replace("/*RGBA*/", RGBA_JS)


_EFFECTIVE_BG = with_rgba(r"""
(el) => {
  /*RGBA*/
  for (let node = el; node; node = node.parentElement) {
    const bg = toRGBA(getComputedStyle(node).backgroundColor);
    if (alphaOf(bg) > 0.05) return bg;
  }
  for (const node of [document.body, document.documentElement]) {
    const bg = toRGBA(getComputedStyle(node).backgroundColor);
    if (alphaOf(bg) > 0.05) return bg;
  }
  return 'rgb(255, 255, 255)';
}
""")
_COLOR_OF = with_rgba("(el, p) => { /*RGBA*/ return toRGBA(getComputedStyle(el).getPropertyValue(p)); }")


def computed(locator: Locator, prop: str) -> str | None:
    """Valor computado de uma propriedade CSS do elemento (None se o elemento sumiu)."""
    try:
        return locator.evaluate("(el, p) => getComputedStyle(el).getPropertyValue(p)", prop, timeout=1500)
    except Exception:  # noqa: BLE001 - elemento removido no meio: sem valor
        return None


def computed_color(locator: Locator | None, prop: str = "color") -> RGB | None:
    """Cor computada de uma propriedade (color, border-top-color...), já convertida para sRGB pelo navegador."""
    if locator is None:
        return None
    try:
        return to_rgb(locator.evaluate(_COLOR_OF, prop, timeout=1500))
    except Exception:  # noqa: BLE001
        return None


def text_color(locator: Locator | None) -> RGB | None:
    return computed_color(locator, "color")


def effective_background(locator: Locator) -> RGB | None:
    """Fundo EFETIVO: sobe pelos ancestrais até achar um `background-color` opaco."""
    try:
        return to_rgb(locator.evaluate(_EFFECTIVE_BG, timeout=1500))
    except Exception:  # noqa: BLE001
        return None
