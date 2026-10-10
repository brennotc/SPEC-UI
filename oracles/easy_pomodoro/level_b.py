"""Nível B de easy_pomodoro: exigências que só a `## Specification` faz (hex, medidas, ARIA, semântica, áudio)."""

import re

from playwright.sync_api import Page

from oracles.common.colors import (
    RGB,
    computed,
    computed_color,
    delta_e,
    text_color,
    to_rgb,
    with_rgba,
)
from oracles.common.geometry import box, visible_all
from oracles.common.locators import (
    audio_plays,
    background_at,
    circle_border_color,
    find_text,
    icon_on_same_row,
    text_of,
)
from oracles.easy_pomodoro.helpers import (
    circle_box,
    click,
    display_text,
    divider_lines,
    footer_label,
    locate,
    period_name,
    read_inputs,
    type_minutes,
)
from specui.oracle import Checks, case

TOLERANCE_DE = 5.0  # ΔE2000: indistinguível a olho nu para cores chapadas
FOCUS, SHORT, LONG = (0xD7, 0x47, 0x47), (0x65, 0x8B, 0x5C), (0x56, 0x84, 0xD9)
HEADER_RED, GRAY = (0xE5, 0x60, 0x60), (0x71, 0x6C, 0x6C)


def _near(actual: RGB | None, expected: RGB) -> bool:
    return actual is not None and delta_e(actual, expected) <= TOLERANCE_DE


def _within(value: float | None, target: float, tolerance: float = 2.0) -> bool:
    return value is not None and abs(value - target) <= tolerance


def _px(value: str | None) -> float | None:
    match = re.match(r"-?[\d.]+", value or "")
    return float(match.group()) if match else None


@case("E-B-01", requirements=["E-S01"], level="B",
      task="Medir o header.",
      expected="70 px de altura, fundo #E56060, ícone e texto 'Pomodoro' brancos.")
def header_spec(page: Page, t: Checks) -> None:
    header = page.locator("header").first
    t.require("existe um <header>", header.count() > 0 and header.is_visible())
    hb = box(header)
    t.ok("altura de 70 px", _within(hb.h if hb else None, 70), f"altura={hb.h if hb else None}")
    t.ok("fundo #E56060 (ΔE ≤ 5)", _near(background_at(page, 720, 20), HEADER_RED), f"fundo={background_at(page, 720, 20)}")
    title = find_text(page, "pomodoro", exact=True)
    t.ok("texto 'Pomodoro' branco", text_color(title) is not None and min(text_color(title)) >= 240, str(text_color(title)) if title else "sem texto")
    icon = icon_on_same_row(page, title)
    icon_fill = computed_color(icon)
    t.ok("ícone do tomate branco", icon_fill is not None and min(icon_fill) >= 240, f"cor={icon_fill}")


@case("E-B-02", requirements=["E-S02"], level="B",
      task="Medir o círculo e as fontes do período e do tempo.",
      expected="Círculo de 503×503 px; nome do período a 36 px; tempo a 128 px; fonte Inter.")
def circle_spec(page: Page, t: Checks) -> None:
    display, _play = locate(page)
    t.require("existe o visor", display is not None)
    cb = circle_box(display)
    t.ok("círculo de 503 × 503 px", bool(cb and _within(cb.w, 503, 3) and _within(cb.h, 503, 3)), f"caixa={cb}")
    t.ok("tempo com fonte 128 px", _within(_px(computed(display, "font-size")), 128, 1))
    name = period_name(page, display)
    t.ok("nome do período com fonte 36 px", name is not None and _within(_px(computed(name, "font-size")), 36, 1))
    family = computed(page.locator("body"), "font-family") or ""
    t.ok("fonte do texto é Inter", "inter" in family.lower() or "inter" in (computed(display, "font-family") or "").lower(), family)


@case("E-B-03", requirements=["E-S03"], level="B",
      task="Ler as cores exatas do modo Foco Total e da linha divisória.",
      expected="Borda #D74747 e linha divisória #716C6C.")
def hex_colors(page: Page, t: Checks) -> None:
    display, _play = locate(page)
    t.require("existe o visor", display is not None)
    border = circle_border_color(display)
    t.ok("borda do círculo #D74747 (ΔE ≤ 5)", _near(border, FOCUS), f"borda={border}")
    db = box(display)
    grays = [c for _y, c in divider_lines(page, db.y1 if db else 0) if c is not None]
    t.ok("linha divisória #716C6C (ΔE ≤ 5)", any(_near(c, GRAY) for c in grays), f"linhas={grays[:4]}")


@case("E-B-04", requirements=["E-S04"], level="B",
      task="Dar play e olhar os inputs; pausar e olhar de novo.",
      expected="Inputs desabilitados enquanto roda e habilitados parado.")
def inputs_disabled_when_running(page: Page, t: Checks) -> None:
    display, play = locate(page)
    t.require("existem visor e botão", display is not None and play is not None)
    fields = read_inputs(page, display)
    t.require("existem os três inputs", len(fields) == 3)
    t.ok("parado: todos habilitados", all(f.is_enabled() for f in fields))
    click(t, "play", play)
    t.advance(1000)
    t.ok("rodando: todos desabilitados", all(f.is_disabled() for f in fields))
    click(t, "pause", play)
    t.ok("pausado: voltam a ficar habilitados", all(f.is_enabled() for f in fields))


@case("E-B-05", requirements=["E-S05", "E-S10"], level="B",
      task="Inspecionar a estrutura da página.",
      expected="Existem <header>, <main> e <section>; os três campos são input type=number.")
def semantics(page: Page, t: Checks) -> None:
    for tag in ("header", "main", "section"):
        t.ok(f"existe <{tag}>", page.locator(tag).count() >= 1)
    display, _play = locate(page)
    fields = read_inputs(page, display)
    t.ok("três campos de configuração", len(fields) == 3)
    t.ok("todos são type=number", all((f.get_attribute("type") or "") == "number" for f in fields))


@case("E-B-06", requirements=["E-S06"], level="B",
      task="Ler o aria-label do botão parado e rodando.",
      expected="'Iniciar temporizador' parado e 'Pausar temporizador' rodando.")
def aria_toggle(page: Page, t: Checks) -> None:
    display, play = locate(page)
    t.require("existem visor e botão", display is not None and play is not None)
    t.ok("parado: aria-label 'Iniciar temporizador'", play.get_attribute("aria-label") == "Iniciar temporizador", str(play.get_attribute("aria-label")))
    click(t, "play", play)
    t.advance(500)
    t.ok("rodando: aria-label 'Pausar temporizador'", play.get_attribute("aria-label") == "Pausar temporizador", str(play.get_attribute("aria-label")))


@case("E-B-07", requirements=["E-S07"], level="B",
      task="Verificar os rótulos dos inputs.",
      expected="Cada input tem ao menos um <label> associado.")
def labels(page: Page, t: Checks) -> None:
    display, _play = locate(page)
    fields = read_inputs(page, display)
    t.require("existem os três inputs", len(fields) == 3)
    for index, field in enumerate(fields, start=1):
        count = field.evaluate("(n) => n.labels ? n.labels.length : 0")
        t.ok(f"input {index} tem <label> associado", count >= 1, f"labels={count}")


@case("E-B-08", requirements=["E-S08"], level="B",
      task="Navegar por teclado até o botão de play.",
      expected="O botão focado exibe anel de foco (outline ou sombra).")
def focus_ring(page: Page, t: Checks) -> None:
    display, play = locate(page)
    t.require("existem visor e botão", display is not None and play is not None)
    reached = False
    for _ in range(14):
        page.keyboard.press("Tab")
        if play.evaluate("(n) => n === document.activeElement"):
            reached = True
            break
    t.require("o botão é alcançável por Tab", reached)
    outline = (computed(play, "outline-style") or "none", _px(computed(play, "outline-width")) or 0)
    shadow = computed(play, "box-shadow") or "none"
    t.ok("o botão focado tem outline ou box-shadow visível", (outline[0] != "none" and outline[1] > 0) or shadow != "none",
         f"outline={outline} shadow={shadow}")


@case("E-B-09", requirements=["E-S09"], level="B",
      task="Medir os três campos de configuração do rodapé.",
      expected="Retângulos de 89×40 px na cor do modo, fonte branca; Foco à esquerda (alinhado à logo), Curta no centro, Longa à direita.")
def footer_layout(page: Page, t: Checks) -> None:
    display, _play = locate(page)
    t.require("existe o visor", display is not None)
    fields = read_inputs(page, display)
    t.require("existem os três inputs", len(fields) == 3)
    expected_colors = (FOCUS, SHORT, LONG)
    groups = []
    for field, color, mode in zip(fields, expected_colors, ("Foco Total", "Pausa Curta", "Pausa Longa"), strict=True):
        rect = _rect(field)
        t.ok(f"{mode}: retângulo de 89 × 40 px", bool(rect and _within(rect[2], 89, 3) and _within(rect[3], 40, 3)), f"retângulo={rect}")
        t.ok(f"{mode}: fundo na cor do modo", _near(_bg(field), color), f"fundo={_bg(field)}")
        ink = text_color(field)
        t.ok(f"{mode}: fonte do input branca", ink is not None and min(ink) >= 240, f"cor={ink}")
        label = footer_label(page, display, mode)
        lb = box(label)
        groups.append((lb.x if lb else None, (rect[0] + rect[2]) if rect else None))
    title_box = box(find_text(page, "pomodoro", exact=True))
    icon_box = box(icon_on_same_row(page, find_text(page, "pomodoro", exact=True)))
    logo_x = icon_box.x if icon_box else (title_box.x if title_box else None)
    (left_x, _), (short_l, short_r), (_, long_r) = groups
    t.ok("Foco Total alinhado à logo (±24 px)", _within(left_x, logo_x, 24) if left_x is not None and logo_x is not None else False,
         f"x={left_x} logo={logo_x}")
    t.ok("Pausa Curta no centro da página (±40 px)",
         short_l is not None and short_r is not None and abs((short_l + short_r) / 2 - 720) <= 40, f"{short_l}..{short_r}")
    t.ok("Pausa Longa no lado oposto de Foco Total (±24 px)",
         left_x is not None and long_r is not None and abs((1440 - long_r) - left_x) <= 24, f"direita={long_r}")


def _rect(field) -> tuple[float, float, float, float] | None:
    """Retângulo 89×40: o próprio input ou o ancestral mais próximo com essa medida."""
    js = """
    (el) => {
      for (let n = el, i = 0; n && i < 4; n = n.parentElement, i++) {
        const r = n.getBoundingClientRect();
        if (Math.abs(r.width - 89) <= 3 && Math.abs(r.height - 40) <= 3) return [r.x, r.y, r.width, r.height];
      }
      const r = el.getBoundingClientRect();
      return [r.x, r.y, r.width, r.height];
    }
    """
    try:
        return tuple(field.evaluate(js, timeout=1500))
    except Exception:  # noqa: BLE001
        return None


def _bg(field) -> RGB | None:
    js = with_rgba(r"""
    (el) => {
      /*RGBA*/
      for (let n = el, i = 0; n && i < 4; n = n.parentElement, i++) {
        const bg = toRGBA(getComputedStyle(n).backgroundColor);
        if (alphaOf(bg) > 0.5) return bg;
      }
      return null;
    }
    """)
    try:
        return to_rgb(field.evaluate(js, timeout=1500))
    except Exception:  # noqa: BLE001
        return None


@case("E-B-10", requirements=["E-S03"], level="B",
      task="Comparar as cores do modo Foco Total em dois pontos.",
      expected="Rótulo e retângulo de Foco Total usam #D74747.")
def label_color(page: Page, t: Checks) -> None:
    display, _play = locate(page)
    label = footer_label(page, display, "Foco Total")
    t.require("existe o rótulo 'Foco Total' no rodapé", label is not None)
    t.ok("rótulo na cor do modo (ΔE ≤ 5)", _near(text_color(label), FOCUS), f"cor={text_color(label)}")
    t.ok("nome do período legível", bool(text_of(period_name(page, display))))
    t.ok("há três rótulos de modo no rodapé", sum(footer_label(page, display, m) is not None for m in ("Foco Total", "Pausa Curta", "Pausa Longa")) == 3)
    t.ok("os rótulos do rodapé estão visíveis", len(visible_all(page.get_by_text(re.compile("Foco Total|Pausa Curta|Pausa Longa")))) >= 3)


@case("E-B-11", requirements=["E-S11"], level="B",
      task="Configurar 1 minuto, dar play e deixar 70 s passarem.",
      expected="O som é disparado (audio.play) e o timer volta ao estado pausado.")
def audio_and_pause_at_end(page: Page, t: Checks) -> None:
    display, play = locate(page)
    t.require("existem visor e botão", display is not None and play is not None)
    fields = read_inputs(page, display)
    t.require("existe o input de Foco Total", len(fields) >= 1)
    t.act("digitar 1 minuto", lambda: _ensure(type_minutes(fields[0], 1)))
    click(t, "play", play)
    for _ in range(14):
        t.advance(5000)
    t.ok("o som foi tocado ao zerar", audio_plays(page) >= 1, f"plays={audio_plays(page)}")
    label = (play.get_attribute("aria-label") or text_of(play) or "").lower()
    t.ok("o botão volta a oferecer iniciar (estado pausado)", bool(re.search(r"iniciar|play|start|retomar", label)) and "paus" not in label, label)
    frozen = display_text(page)
    t.advance(3000)
    t.ok("a contagem não continua depois de pausar", display_text(page) == frozen, f"{frozen} -> {display_text(page)}")


def _ensure(done: bool) -> None:
    if not done:
        raise ValueError("input não aceitou o valor")
