"""Nível A de hard_kanban: só o que o `## Prompt` permite verificar. Os cards são criados pela UI (PD-H1)."""

import contextlib

from playwright.sync_api import Page

from oracles.common.colors import (
    effective_background,
    hue_bucket,
    hue_matches,
    relative_luminance,
    text_color,
    with_rgba,
)
from oracles.common.dnd import DndDriver
from oracles.common.geometry import box, visible_all
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
from oracles.common.probes import is_light
from oracles.hard_kanban.helpers import (
    body_color,
    check_and_cancel,
    column_index,
    column_rect,
    input_in_column,
    is_off_white,
    move_to_column,
    need_cards,
    placeholder,
    ranges,
    start_creation,
    title_boxes,
)
from specui.oracle import Checks, case

HUES = ("blue", "orange", "purple", "green")


@case("H-A-01", requirements=["H-01"], level="A",
      task="Abrir a página.",
      expected="Header verde com ícone de lista e 'Kanban' no canto superior esquerdo; fundo geral cinza.")
def page_and_header(page: Page, t: Checks) -> None:
    title = find_text(page, "kanban", exact=True)
    t.require("o texto 'Kanban' aparece", title is not None)
    tb = box(title)
    t.ok("o título está no canto superior esquerdo", bool(tb and tb.x < 400 and tb.y1 < 150), f"{tb}")
    t.ok("há um ícone à esquerda do título", icon_on_same_row(page, title) is not None)
    bg = background_at(page, 720, 20)
    t.ok("o header é verde", hue_matches(bg, "green"), f"fundo={bg}")
    probes = [background_at(page, x, y) for x, y in ((2, 450), (1437, 450), (720, 897), (2, 897))]
    probes.append(effective_background(page.locator("body")))
    grays = [p for p in probes if p is not None and hue_bucket(p) == "gray" and 0.25 < relative_luminance(p) < 0.95]
    t.ok("o fundo geral da página é cinza", bool(grays), f"amostras={probes}")


@case("H-A-02", requirements=["H-02", "H-03"], level="A",
      task="Olhar o corpo da página.",
      expected="Quatro colunas lado a lado, de mesma largura, ocupando a tela, tituladas Para Fazer, Em Progresso, Feito, Aprovado.")
def four_columns(page: Page, t: Checks) -> None:
    boxes = title_boxes(page)
    for title, b in zip(COLUMN_TITLES, boxes, strict=True):
        t.ok(f"existe a coluna '{title}'", b is not None)
    t.require("os quatro títulos existem", all(boxes))
    t.ok("títulos na ordem esquerda → direita", [b.cx for b in boxes] == sorted(b.cx for b in boxes))
    rects = [column_rect(page, i) for i in range(4)]
    widths = [r[0].w for r in rects if r]
    t.require("o cabeçalho de cada coluna é um retângulo", len(widths) == 4)
    t.ok("as quatro colunas têm a mesma largura (±2 %)", max(widths) - min(widths) <= 0.02 * max(widths), f"larguras={widths}")
    t.ok("as colunas ocupam a tela (≥ 85 % da largura)", sum(widths) >= 0.85 * 1440, f"soma={sum(widths)}")
    t.ok("as colunas ficam abaixo do header", all(r[0].y >= 60 for r in rects if r))


@case("H-A-03", requirements=["H-04"], level="A",
      task="Olhar o cabeçalho e o corpo de cada coluna.",
      expected="Cabeçalho azul, laranja, roxo e verde com título branco; corpo da coluna em tom mais claro.")
def column_colors(page: Page, t: Checks) -> None:
    for index, (title, hue) in enumerate(zip(COLUMN_TITLES, HUES, strict=True)):
        rect = column_rect(page, index)
        t.ok(f"'{title}': cabeçalho {hue}", bool(rect and hue_matches(rect[1], hue)), f"{rect[1] if rect else None}")
        ink = text_color(find_text(page, title, exact=True))
        t.ok(f"'{title}': título em branco", is_light(ink, 235), f"{ink}")
        body = body_color(page, index)
        header = rect[1] if rect else None
        t.ok(f"'{title}': o corpo é mais claro que o cabeçalho",
             bool(body and header and relative_luminance(body) > relative_luminance(header) + 0.05), f"{body} vs {header}")
        if title != "Aprovado":  # PD-H6: o corpo do Aprovado (#C5CC9E, da spec) cai na faixa do amarelo: só a luminância
            t.ok(f"'{title}': corpo da mesma família de cor", hue_matches(body, hue), f"{body}")


@case("H-A-04", requirements=["H-06"], level="A",
      task="Olhar o final da primeira coluna e das demais.",
      expected="Só a coluna Para Fazer tem o card esmaecido com contorno dashed e um + no centro.")
def placeholder_card(page: Page, t: Checks) -> None:
    col_ranges = ranges(page)
    t.require("as quatro colunas existem", col_ranges is not None)
    first = placeholder(page, col_ranges, 0)
    t.require("existe um card com contorno dashed na primeira coluna", first is not None)  # efeito principal
    for index in (1, 2, 3):
        t.ok(f"a coluna '{COLUMN_TITLES[index]}' não tem card dashed", placeholder(page, col_ranges, index) is None)
    t.ok("há um + no centro do card esmaecido", _plus_at_center(page, first))
    t.ok("o card esmaecido está esmaecido (opacidade, fundo ou contorno translúcidos)", _dim_at(page, first),
         "o placeholder parece opaco")


# "Esmaecido" e "ícone de +" não têm mecanismo no prompt (regra 2): vale opacidade OU fundo/contorno translúcidos,
# e vale um "+" em texto, num botão ou num ícone (svg/img) no centro do card. O `opacity-70` é da spec (nível B).
_DIM_JS = with_rgba(r"""
([x, y]) => {
  /*RGBA*/
  let o = 1;
  const start = document.elementFromPoint(x, y);
  for (let n = start; n && n !== document.documentElement; n = n.parentElement) o *= parseFloat(getComputedStyle(n).opacity);
  if (o < 0.99) return true;
  for (let n = start, i = 0; n && i < 8; n = n.parentElement, i++) {  // o centro pode cair no svg do +
    const cs = getComputedStyle(n);
    if (cs.borderTopStyle === 'dashed') {
      const bg = alphaOf(toRGBA(cs.backgroundColor)), border = alphaOf(toRGBA(cs.borderTopColor));
      return (bg > 0 && bg < 0.9) || border < 0.9;
    }
  }
  return false;
}
""")


def _dim_at(page: Page, b) -> bool:
    try:
        return bool(page.evaluate(_DIM_JS, [b.cx, b.cy]))
    except Exception:  # noqa: BLE001
        return False


def _plus_at_center(page: Page, b) -> bool:
    """Um "+" (texto, botão nomeado ou ícone svg/img) cujo centro cai no terço central do card esmaecido."""
    import re

    named = page.get_by_role("button", name=re.compile(r"adicion|add|nov[ao]|criar|\+", re.IGNORECASE))
    candidates = [*visible_all(page.get_by_text("+", exact=True)), *visible_all(named), *visible_all(page.locator("svg, img"))]
    for c in candidates:
        cb = box(c)
        if cb and abs(cb.cx - b.cx) <= b.w / 3 and abs(cb.cy - b.cy) <= b.h / 3 and cb.w < b.w * 0.8:
            return True
    return False


@case("H-A-05", requirements=["H-07"], level="A",
      task="Clicar no + do card esmaecido.",
      expected="Surge um input no centro do card e, no canto superior direito, um check verde e um X vermelho.")
def creation_mode(page: Page, t: Checks) -> None:
    field = start_creation(page)
    t.require("aparece um input na primeira coluna", field is not None)
    fb = box(field)
    container = card_container(field)
    cb = box(container)
    t.ok("o input fica no centro do card", bool(fb and cb and abs(fb.cx - cb.cx) < 0.2 * cb.w and abs(fb.cy - cb.cy) < 0.3 * cb.h), f"{fb} {cb}")
    check, cancel = check_and_cancel(field)
    t.ok("há um ícone de check", check is not None)
    t.ok("há um ícone de X", cancel is not None)
    kb, xb = box(check), box(cancel)
    t.ok("os ícones ficam no canto superior direito do card, check antes do X",
         bool(kb and xb and cb and kb.cx < xb.cx and xb.cx > cb.cx and kb.cy < cb.cy), f"{kb} {xb} {cb}")
    t.ok("o check é verde", hue_matches(icon_color(check), "green"), f"{icon_color(check)}")
    t.ok("o X é vermelho", hue_matches(icon_color(cancel), "red"), f"{icon_color(cancel)}")
    t.ok("o card em criação deixa de ser esmaecido (cor dos demais)", bool(cb) and is_off_white(background_at(page, cb.x + 8, cb.y + cb.h - 8)),
         f"{background_at(page, cb.x + 8, cb.y + cb.h - 8) if cb else None}")


@case("H-A-06", requirements=["H-08"], level="A",
      task="Criar o card 'Novo Card de Teste' (+, digitar, check) e depois outro, 'Segundo Card'.",
      expected="O card aparece na primeira coluna, os novos ficam em ordem de criação e o card esmaecido volta.")
def confirm_creates_card(page: Page, t: Checks) -> None:
    col_ranges = ranges(page)
    t.require("as quatro colunas existem", col_ranges is not None)
    need_cards(page, t, ["Novo Card de Teste", "Segundo Card"])  # efeito principal: +, digitar e check criam os cards
    t.ok("o card está na coluna Para Fazer", column_index(page, col_ranges, "Novo Card de Teste") == 0)
    ph = placeholder(page, col_ranges)  # rola até o fim da coluna ANTES de medir: todas as caixas no mesmo referencial
    first, second = box(card_text(page, "Novo Card de Teste")), box(card_text(page, "Segundo Card"))
    t.ok("os cards ficam na ordem em que foram criados (o novo por último)", bool(first and second and first.cy < second.cy), f"{first} {second}")
    t.ok("o card esmaecido volta ao final da coluna", bool(ph and second and ph.cy > second.cy), f"{ph}")
    t.ok("o input de criação some", input_in_column(page, col_ranges) is None)


@case("H-A-07", requirements=["H-09"], level="A",
      task="Clicar no +, digitar 'Descartar' e clicar no X.",
      expected="O card não é criado e o card esmaecido volta ao estado inicial.")
def cancel_creation(page: Page, t: Checks) -> None:
    col_ranges = ranges(page)
    t.require("as quatro colunas existem", col_ranges is not None)
    field = start_creation(page)
    t.require("o modo de criação abre", field is not None)
    t.act("digitar a descrição", lambda: field.fill("Descartar"))
    _check, cancel = check_and_cancel(field)
    t.require("existe o X", cancel is not None)
    t.act("clicar no X", lambda: cancel.click(timeout=2000))
    page.wait_for_timeout(500)
    t.ok("o card não foi criado", card_text(page, "Descartar") is None)
    t.ok("o input de criação some", input_in_column(page, col_ranges) is None)
    t.ok("o card esmaecido volta", placeholder(page, col_ranges) is not None)


@case("H-A-08", requirements=["H-05"], level="A",
      task="Criar um card e olhar a sua aparência.",
      expected="Card off-white, mais claro que a coluna, com bordas arredondadas, lápis azul e lixeira vermelha no canto superior direito e a descrição em preto no centro.")
def card_look(page: Page, t: Checks) -> None:
    need_cards(page, t, ["Aparencia"])
    text = card_text(page, "Aparencia")
    container = card_container(text)
    cb, tb = box(container), box(text)
    t.require("o card tem um contêiner", cb is not None)
    t.ok("fundo off-white (claro e pouco saturado)", is_off_white(effective_background(container)), f"{effective_background(container)}")
    column_bg = background_at(page, cb.x - 6, cb.cy)
    t.ok("o card é mais claro que o corpo da coluna", bool(column_bg) and relative_luminance(effective_background(container)) > relative_luminance(column_bg), f"{column_bg}")
    radius = container.evaluate("(n) => parseFloat(getComputedStyle(n).borderTopLeftRadius) || 0")
    t.ok("bordas arredondadas", radius > 2, f"raio={radius}")
    ink = text_color(text)
    t.ok("descrição em preto", ink is not None and max(ink) <= 60, f"{ink}")
    t.ok("descrição no centro do card", bool(tb and abs(tb.cx - cb.cx) < 0.15 * cb.w and abs(tb.cy - cb.cy) < 0.3 * cb.h), f"{tb} {cb}")
    actions = card_actions(page, "Aparencia")
    t.ok("há lápis e lixeira", actions["edit"] is not None and actions["delete"] is not None)
    eb, db = box(actions["edit"]), box(actions["delete"])
    t.ok("lápis e lixeira ficam no canto superior direito, o lápis antes da lixeira",
         bool(eb and db and eb.cx < db.cx and db.cx > cb.cx and db.cy < cb.cy), f"{eb} {db}")
    t.ok("o lápis é azul", hue_matches(icon_color(actions["edit"]), "blue"), f"{icon_color(actions['edit'])}")
    t.ok("a lixeira é vermelha", hue_matches(icon_color(actions["delete"]), "red"), f"{icon_color(actions['delete'])}")


@case("H-A-09", requirements=["H-05"], level="A",
      task="Criar um card e clicar na lixeira.",
      expected="O card some da coluna e os outros permanecem.")
def delete_card(page: Page, t: Checks) -> None:
    need_cards(page, t, ["Apagar este", "Manter este"])
    actions = card_actions(page, "Apagar este")
    t.require("o card tem lixeira", actions["delete"] is not None)
    t.act("clicar na lixeira", lambda: actions["delete"].click(timeout=2000))
    page.wait_for_timeout(400)
    t.ok("o card excluído some", card_text(page, "Apagar este") is None)
    t.ok("o outro card permanece", card_text(page, "Manter este") is not None)
    t.ok("o card esmaecido continua no final da coluna", placeholder(page, ranges(page)) is not None)


@case("H-A-10", requirements=["H-10"], level="A",
      task="Criar um card e olhar o ícone de lixeira.",
      expected="A lixeira vermelha existe em todo card.")
def trash_on_every_card(page: Page, t: Checks) -> None:
    need_cards(page, t, ["Lixeira 1", "Lixeira 2"])
    for description in ("Lixeira 1", "Lixeira 2"):
        actions = card_actions(page, description)
        t.ok(f"'{description}' tem lixeira vermelha", actions["delete"] is not None and hue_matches(icon_color(actions["delete"]), "red"))


@case("H-A-11", requirements=["H-12"], level="A",
      task="Arrastar um card de Para Fazer para Em Progresso.",
      expected="O card muda para a coluna Em Progresso.")
def drag_one_step_right(page: Page, t: Checks) -> None:
    col_ranges = ranges(page)
    t.require("as quatro colunas existem", col_ranges is not None)
    need_cards(page, t, ["Mover 1"])
    t.require("o card começa em Para Fazer", column_index(page, col_ranges, "Mover 1") == 0)
    driver = DndDriver(page)
    t.require("o card muda para Em Progresso", move_to_column(page, driver, "Mover 1", col_ranges, 1))  # efeito principal
    t.ok("o card só existe uma vez", page.get_by_text("Mover 1", exact=True).count() == 1)


@case("H-A-12", requirements=["H-13"], level="A",
      task="Tentar arrastar cards de Para Fazer para Feito e de Em Progresso para Aprovado.",
      expected="Os cards voltam à coluna de origem (não se pode pular etapas à direita).")
def drag_cannot_skip_right(page: Page, t: Checks) -> None:
    col_ranges = ranges(page)
    t.require("as quatro colunas existem", col_ranges is not None)
    need_cards(page, t, ["Pular A", "Pular B"])
    driver = DndDriver(page)
    t.require("o gesto de arrastar funciona num movimento permitido", move_to_column(page, driver, "Pular B", col_ranges, 1))
    t.ok("Para Fazer → Feito é recusado", not move_to_column(page, driver, "Pular A", col_ranges, 2, expect_move=False))
    t.ok("o card recusado continua em Para Fazer", column_index(page, col_ranges, "Pular A") == 0)
    t.ok("Em Progresso → Aprovado é recusado", not move_to_column(page, driver, "Pular B", col_ranges, 3, expect_move=False))
    t.ok("o card recusado continua em Em Progresso", column_index(page, col_ranges, "Pular B") == 1)
    t.ok("Para Fazer → Aprovado é recusado", not move_to_column(page, driver, "Pular A", col_ranges, 3, expect_move=False))
    t.ok("nenhum card se perdeu", card_text(page, "Pular A") is not None and card_text(page, "Pular B") is not None)


@case("H-A-13", requirements=["H-14"], level="A",
      task="Levar um card até Aprovado, um passo por vez, e arrastá-lo de volta para Para Fazer.",
      expected="O recuo de vários passos à esquerda é permitido.")
def drag_back_many_steps(page: Page, t: Checks) -> None:
    col_ranges = ranges(page)
    t.require("as quatro colunas existem", col_ranges is not None)
    need_cards(page, t, ["Voltar"])
    driver = DndDriver(page)
    for step in (1, 2, 3):
        t.require(f"avançar o card para '{COLUMN_TITLES[step]}'", move_to_column(page, driver, "Voltar", col_ranges, step))
    t.ok("de Aprovado para Para Fazer (3 passos)", move_to_column(page, driver, "Voltar", col_ranges, 0))
    t.require("o card voltou", column_index(page, col_ranges, "Voltar") == 0)
    t.ok("de Para Fazer a Em Progresso de novo e de volta (1 passo à esquerda)",
         move_to_column(page, driver, "Voltar", col_ranges, 1) and move_to_column(page, driver, "Voltar", col_ranges, 0))


@case("H-A-14", requirements=["H-15"], level="A",
      task="Criar três cards na mesma coluna e arrastar o segundo para cima do primeiro.",
      expected="A ordem vertical dos cards da coluna muda.")
def reorder_within_column(page: Page, t: Checks) -> None:
    col_ranges = ranges(page)
    t.require("as quatro colunas existem", col_ranges is not None)
    need_cards(page, t, ["Ordem A", "Ordem B", "Ordem C"])
    driver = DndDriver(page)
    # cards vizinhos (A e B) cabem juntos na tela; o C pode estar abaixo da área visível
    with contextlib.suppress(Exception):
        card_container(card_text(page, "Ordem A")).first.evaluate("(n) => n.scrollIntoView({ block: 'start' })")
    target = box(card_container(card_text(page, "Ordem A")).first) if card_text(page, "Ordem A") else None
    t.require("há um card para servir de alvo", target is not None)
    src = card_text(page, "Ordem B")

    def moved() -> bool:
        b, a = box(card_text(page, "Ordem B")), box(card_text(page, "Ordem A"))
        return bool(b and a and b.cy < a.cy)

    t.require("arrastar o card B para cima do A reordena a coluna",
              driver.move_until(src, (target.cx, target.y + 0.25 * target.h), moved))  # efeito principal
    t.ok("o card continua na mesma coluna", column_index(page, col_ranges, "Ordem B") == 0)
    t.ok("nenhum card se perdeu", all(card_text(page, d) is not None for d in ("Ordem A", "Ordem B", "Ordem C")))


@case("H-A-15", requirements=["H-11"], level="A", pending="PD-H2",
      task="Clicar no lápis de um card.",
      expected="O card pode ser editado (o mecanismo não é descrito no prompt: pendente).")
def edit_flow(page: Page, t: Checks) -> None:
    t.pending("a edição altera a descrição", "PD-H2")
