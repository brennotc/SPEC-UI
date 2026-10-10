"""Nível A de easy_pomodoro: só o que o `## Prompt` permite verificar (cores por faixa de matiz, sem hex)."""

import re

from playwright.sync_api import Page

from oracles.common.colors import hue_matches
from oracles.common.geometry import box
from oracles.common.locators import (
    background_at,
    circle_border_color,
    find_text,
    icon_on_same_row,
    text_of,
    wait_display,
)
from oracles.easy_pomodoro.helpers import (
    click,
    display_text,
    divider_lines,
    input_minutes,
    is_grayish,
    locate,
    read_inputs,
    seconds,
    type_minutes,
)
from specui.oracle import Checks, case

MMSS = re.compile(r"^\d{1,2}:\d{2}$")


@case("E-A-01", requirements=["E-04", "E-05", "E-06"], level="A",
      task="Abrir a página sem interagir.",
      expected="Aparecem o nome do período 'Foco Total', o tempo 25:00 e um botão de play/pause.")
def initial_state(page: Page, t: Checks) -> None:
    display, play = locate(page)
    t.require("existe um visor no formato MM:SS", display is not None)
    t.ok("visor mostra 25:00", display_text(page) == "25:00", display_text(page))
    t.ok("aparece 'Foco Total' acima do visor", _period_above(page, display))
    t.ok("existe botão de play/pause", play is not None)
    pb, db = box(play), box(display)
    t.ok("o botão fica abaixo do visor", bool(pb and db and pb.cy > db.cy), "botão fora de posição")


def _period_above(page: Page, display) -> bool:
    from oracles.easy_pomodoro.helpers import period_name

    name = period_name(page, display)
    return name is not None and "foco total" in text_of(name).lower()


@case("E-A-02", requirements=["E-02"], level="A",
      task="Olhar o topo da página.",
      expected="Header vermelho claro; ícone de tomate à esquerda do texto 'Pomodoro', no canto superior esquerdo.")
def header(page: Page, t: Checks) -> None:
    title = find_text(page, "pomodoro", exact=True)
    t.require("o texto 'Pomodoro' aparece", title is not None)
    tb = box(title)
    t.ok("'Pomodoro' está no canto superior esquerdo", bool(tb and tb.x < 400 and tb.y1 < 150), f"caixa={tb}")
    t.ok("há um ícone na mesma linha, à esquerda do texto", icon_on_same_row(page, title) is not None)
    bg = background_at(page, 720, 20)
    t.ok("o topo da página é vermelho (header)", hue_matches(bg, "red"), f"fundo={bg}")


@case("E-A-03", requirements=["E-01"], level="A",
      task="Olhar o fundo da página, fora do header e do círculo.",
      expected="O fundo é branco.")
def white_page(page: Page, t: Checks) -> None:
    for name, (x, y) in {"à esquerda do círculo": (60, 450), "à direita do círculo": (1380, 450)}.items():
        bg = background_at(page, x, y)
        t.ok(f"fundo branco {name}", bg is not None and min(bg) >= 245, f"fundo={bg}")


@case("E-A-04", requirements=["E-03", "E-04"], level="A",
      task="Olhar o círculo central no estado inicial.",
      expected="Um círculo com borda vermelha, centralizado, contendo o visor; o nome do período fica acima do visor.")
def circle(page: Page, t: Checks) -> None:
    display, _play = locate(page)
    t.require("existe um visor", display is not None)
    border = circle_border_color(display)
    t.ok("o visor está dentro de um círculo com borda", border is not None)
    t.ok("a borda inicial é vermelha (Foco Total)", hue_matches(border, "red"), f"borda={border}")
    db = box(display)
    t.ok("o visor está no centro horizontal da página", bool(db and abs(db.cx - 720) < 90), f"cx={db.cx if db else None}")


@case("E-A-05", requirements=["E-05", "E-06"], level="A",
      task="Clicar em play e deixar 3 segundos passarem.",
      expected="O visor mostra 24:57.")
def play_counts_down(page: Page, t: Checks) -> None:
    display, play = locate(page)
    t.require("existem visor e botão", display is not None and play is not None)
    click(t, "clicar em play", play)
    t.advance(3000)
    t.eventually("visor mostra 24:57 após 3 s", lambda: wait_display(page, "24:57", 800))
    t.ok("o visor continua no formato MM:SS", bool(MMSS.match(display_text(page))), display_text(page))


@case("E-A-06", requirements=["E-06"], level="A",
      task="Dar play, esperar 2 s, pausar, esperar 3 s, dar play de novo e esperar 2 s.",
      expected="Pausado, o visor não muda; ao retomar, volta a decrescer.")
def pause_and_resume(page: Page, t: Checks) -> None:
    display, play = locate(page)
    t.require("existem visor e botão", display is not None and play is not None)
    click(t, "play", play)
    t.advance(2000)
    t.require("a contagem começou", (seconds(display_text(page)) or 1500) < 1500)
    click(t, "pause", play)
    frozen = display_text(page)
    t.advance(3000)
    t.ok("pausado, o visor não muda", display_text(page) == frozen, f"{frozen} -> {display_text(page)}")
    click(t, "play de novo", play)
    t.advance(2000)
    after, before = seconds(display_text(page)), seconds(frozen)
    t.ok("ao retomar, o visor volta a decrescer", bool(after is not None and before is not None and after < before),
         f"{frozen} -> {display_text(page)}")


@case("E-A-07", requirements=["E-07", "E-08"], level="A",
      task="Olhar o rodapé.",
      expected="Linha cinza de divisão e, abaixo dela, três inputs com 25, 5 e 15 minutos para Foco Total, Pausa Curta e Pausa Longa.",
      )
def footer_defaults(page: Page, t: Checks) -> None:
    display, _play = locate(page)
    t.require("existe um visor", display is not None)
    fields = read_inputs(page, display)
    t.ok("há três inputs abaixo do visor", len(fields) == 3, f"encontrados={len(fields)}")
    values = [input_minutes(f) for f in fields[:3]]
    t.ok("os valores padrão são 25, 5 e 15 minutos", values == [25, 5, 15], f"valores={values}")
    for mode in ("Foco Total", "Pausa Curta", "Pausa Longa"):
        label = [x for x in _below(page, display, mode)]
        t.ok(f"rodapé nomeia '{mode}'", bool(label))
    db = box(display)
    lines = divider_lines(page, db.y1 if db else 0)
    grays = [y for y, color in lines if is_grayish(color)]
    first_input = box(fields[0]) if fields else None
    t.ok("há uma linha cinza de divisão acima dos inputs",
         bool(first_input and any(db and db.y1 < y < first_input.y for y in grays)), f"linhas={lines[:4]}")


def _below(page: Page, display, mode: str):
    from oracles.easy_pomodoro.helpers import footer_label

    label = footer_label(page, display, mode)
    return [label] if label is not None else []


@case("E-A-08", requirements=["E-09"], level="A",
      task="Com o timer parado, mudar o input de Foco Total de 25 para 30.",
      expected="O visor passa a mostrar 30:00 (ou 29:59 um segundo depois de iniciar).")
def edit_focus_time(page: Page, t: Checks) -> None:
    display, play = locate(page)
    t.require("existem visor e botão", display is not None and play is not None)
    fields = read_inputs(page, display)
    t.require("existe o input de Foco Total", len(fields) >= 1)
    t.act("digitar 30 no input de Foco Total", lambda: _must(type_minutes(fields[0], 30)))
    page.wait_for_timeout(200)
    t.ok("o input guarda 30", input_minutes(fields[0]) == 30, str(input_minutes(fields[0])))
    if display_text(page) == "30:00":
        t.ok("o visor reflete os 30 minutos", True)
        return
    # leitura alternativa do prompt: a configuração vale a partir do próximo play
    click(t, "play", play)
    t.advance(1000)
    t.ok("o visor reflete os 30 minutos (29:59 após 1 s)", display_text(page) == "29:59", display_text(page))


def _must(done: bool) -> None:
    if not done:
        raise ValueError("input não aceitou o valor")


@case("E-A-09", requirements=["E-12"], level="A",
      task="Configurar 1 minuto, dar play e deixar passar 70 s.",
      expected="O visor nunca mostra valor negativo ou NaN e a página não lança erro.")
def countdown_ends_cleanly(page: Page, t: Checks) -> None:
    display, play = locate(page)
    t.require("existem visor e botão", display is not None and play is not None)
    fields = read_inputs(page, display)
    t.require("existe o input de Foco Total", len(fields) >= 1)
    t.act("digitar 1 minuto", lambda: _must(type_minutes(fields[0], 1)))
    click(t, "play", play)
    seen: list[str] = []
    for _ in range(14):
        t.advance(5000)
        seen.append(display_text(page))
    bad = [s for s in seen if not MMSS.match(s)]
    t.ok("o visor sempre mostra MM:SS (sem '-' nem NaN)", not bad, f"leituras inválidas={bad[:3]}")
    t.ok("a contagem chegou a decrescer", any((seconds(s) or 99999) < 60 for s in seen), f"leituras={seen}")
    t.ok("nenhum erro de página durante o fim da contagem", not t.js_errors(), "; ".join(t.js_errors()))


@case("E-A-10", requirements=["E-10"], level="A", pending="PD-E2",
      task="Trocar para Pausa Curta e Pausa Longa.",
      expected="Borda verde e azul (mecanismo de troca não descrito no prompt: pendente).")
def mode_colors(page: Page, t: Checks) -> None:
    t.pending("borda verde em Pausa Curta e azul em Pausa Longa", "PD-E2")


@case("E-A-11", requirements=["E-03"], level="A",
      task="Olhar o círculo no início e ao rodar.",
      expected="O círculo mantém a borda vermelha enquanto roda em Foco Total.")
def border_stays_red_while_running(page: Page, t: Checks) -> None:
    display, play = locate(page)
    t.require("existem visor e botão", display is not None and play is not None)
    click(t, "play", play)
    t.advance(2000)
    border = circle_border_color(display)
    t.ok("a borda continua vermelha em Foco Total rodando", hue_matches(border, "red"), f"borda={border}")
