"""Nível A de medium_tarefas: só o que o `## Prompt` permite verificar. Os dados são criados pela UI (PD-M2)."""

import re

from playwright.sync_api import Page

from oracles.common.colors import hue_matches, is_dark, text_color
from oracles.common.dates import LATER, TODAY, TOMORROW, clear_date, fill_date, heading_pattern
from oracles.common.geometry import box, first_visible
from oracles.common.locators import (
    background_at,
    commit,
    find_task_form,
    find_text,
    icon_on_same_row,
    row_actions,
    row_of,
    select_priority,
)
from oracles.common.probes import filled_rect, is_light
from oracles.medium_tarefas.helpers import (
    badge_in,
    checkbox_in,
    heading_y,
    need_tasks,
    rows_top_to_bottom,
    sorted_left_to_right,
)
from specui.oracle import Checks, case

BADGES = {"URGENTE": "red", "MÉDIO": "yellow", "RELAXA": "green"}


@case("M-A-01", requirements=["M-01"], level="A",
      task="Abrir a página.",
      expected="Fundo preto; header azul com ícone de lista e o texto 'Tarefas Para Fazer' no canto superior esquerdo.")
def page_and_header(page: Page, t: Checks) -> None:
    title = find_text(page, "tarefas para fazer", exact=True)
    t.require("o texto 'Tarefas Para Fazer' aparece", title is not None)
    tb = box(title)
    t.ok("o título está no canto superior esquerdo", bool(tb and tb.x < 400 and tb.y1 < 150), f"caixa={tb}")
    t.ok("há um ícone à esquerda do título", icon_on_same_row(page, title) is not None)
    header_bg = background_at(page, 720, 20)
    t.ok("o header é azul", hue_matches(header_bg, "blue"), f"fundo={header_bg}")
    body_bg = background_at(page, 1400, 560)
    t.ok("o fundo da página é preto", is_dark(body_bg, 0.03), f"fundo={body_bg}")


@case("M-A-02", requirements=["M-02"], level="A",
      task="Olhar abaixo do header.",
      expected="Filtro de Data e, ao lado, filtro de Prioridade (seleção), alinhados à esquerda, abaixo do header.")
def filters_row(page: Page, t: Checks) -> None:
    form = find_task_form(page)
    t.ok("existe o filtro de data", form.filter_date is not None)
    t.ok("existe o filtro de prioridade (seleção)", form.filter_priority is not None)
    t.ok("há o rótulo 'Data'", find_text(page, r"data\s*:?", exact=True) is not None)
    t.ok("há o rótulo 'Prioridade' acima do formulário", _count_priority_labels(page) >= 1)
    d, p = box(form.filter_date), box(form.filter_priority)
    t.ok("os filtros ficam abaixo do header (y ≥ 70)", bool(d and p and d.y >= 70 and p.y >= 70), f"{d} {p}")
    t.ok("os filtros ficam na metade esquerda da tela", bool(d and p and d.x < 720 and p.x < 900), f"{d} {p}")
    t.ok("o filtro de prioridade fica ao lado (à direita) do de data", sorted_left_to_right(form.filter_date, form.filter_priority))


def _count_priority_labels(page: Page) -> int:
    return page.get_by_text(re.compile(r"^\s*prioridade\s*:?\s*$", re.IGNORECASE)).count()


@case("M-A-03", requirements=["M-10"], level="A",
      task="Olhar o rodapé de criação.",
      expected="'Nova tarefa:', input de data, seleção de Prioridade, input 'Descrição da tarefa' e ícone + no extremo direito.")
def footer_form(page: Page, t: Checks) -> None:
    form = find_task_form(page)
    t.ok("existe o texto 'Nova tarefa'", find_text(page, r"nova\s+tarefa\s*:?", exact=True) is not None)
    t.ok("existe o input de data do formulário", form.date is not None)
    t.ok("existe a seleção de prioridade do formulário", form.priority is not None)
    t.ok("existe o input 'Descrição da tarefa'", form.description is not None)
    t.ok("existe o ícone/botão de adicionar", form.add is not None)
    t.ok("data, prioridade, descrição e + aparecem nessa ordem, da esquerda para a direita",
         sorted_left_to_right(form.date, form.priority, form.description, form.add))
    add_box = box(form.add)
    t.ok("o + fica no extremo direito da tela", bool(add_box and add_box.cx > 1200), f"caixa={add_box}")
    label, fb = find_text(page, r"nova\s+tarefa\s*:?", exact=True), box(form.date)
    lb = box(label)
    t.ok("'Nova tarefa:' fica no canto esquerdo, antes do input de data", bool(lb and fb and lb.x < 300 and lb.cx < fb.cx))


@case("M-A-04", requirements=["M-11"], level="A",
      task="Preencher data (hoje), prioridade URGENTE e a descrição 'Testar prompt Spec-Driven' e clicar no +.",
      expected="A tarefa aparece na lista com a badge URGENTE e o nome.")
def add_task_case(page: Page, t: Checks) -> None:
    form = find_task_form(page)
    t.require("o formulário do rodapé está completo", all((form.date, form.priority, form.description, form.add)))
    t.act("preencher a data de hoje", lambda: _must(fill_date(form.date, TODAY)))
    t.act("selecionar URGENTE", lambda: _must(select_priority(form.priority, "URGENTE")))
    t.act("digitar a descrição", lambda: form.description.fill("Testar prompt Spec-Driven"))
    t.act("clicar no +", lambda: form.add.click(timeout=2000))
    page.wait_for_timeout(250)
    row = row_of(page, "Testar prompt Spec-Driven")
    t.require("o nome da tarefa aparece em uma linha com checkbox", row is not None)  # efeito principal
    t.ok("a badge URGENTE aparece na linha", badge_in(row, "URGENTE") is not None)
    t.ok("o título do grupo 'Hoje' aparece", heading_y(page, "Hoje", exact=True) is not None)


def _must(done: bool) -> None:
    if not done:
        raise ValueError("o controle não aceitou o valor")


@case("M-A-05", requirements=["M-03"], level="A",
      task="Criar tarefas para um dia escrito, para amanhã e para hoje (nessa ordem) e olhar a lista.",
      expected="Grupos na ordem Hoje, Amanhã e a data escrita, cada tarefa sob o seu grupo.")
def grouping_and_order(page: Page, t: Checks) -> None:
    need_tasks(page, t, [(LATER, "RELAXA", "Tarefa Depois"), (TOMORROW, "MÉDIO", "Tarefa Amanha"), (TODAY, "URGENTE", "Tarefa Hoje")])
    hoje = heading_y(page, "Hoje", exact=True)
    amanha = heading_y(page, r"Amanh[ãa]", exact=True)
    depois = heading_y(page, heading_pattern(LATER))
    t.ok("existe o grupo 'Hoje'", hoje is not None)
    t.ok("existe o grupo 'Amanhã'", amanha is not None)
    t.ok("existe o grupo com a data escrita", depois is not None)
    t.ok("ordem dos grupos: Hoje, Amanhã, depois a data", None not in (hoje, amanha, depois) and hoje < amanha < depois,
         f"{hoje} {amanha} {depois}")
    order = rows_top_to_bottom(page, ["Tarefa Hoje", "Tarefa Amanha", "Tarefa Depois"])
    t.ok("cada tarefa aparece sob o seu grupo (de cima para baixo)", order == ["Tarefa Hoje", "Tarefa Amanha", "Tarefa Depois"], str(order))


@case("M-A-06", requirements=["M-04"], level="A",
      task="Criar uma tarefa de cada prioridade e olhar as badges.",
      expected="URGENTE vermelha, MÉDIO amarela e RELAXA verde, todas com texto branco.")
def badge_colors(page: Page, t: Checks) -> None:
    need_tasks(page, t, [(TODAY, word, f"Badge {word}") for word in BADGES])
    for word, hue in BADGES.items():
        row = row_of(page, f"Badge {word}")
        badge = badge_in(row, word) if row is not None else None
        t.ok(f"existe a badge {word}", badge is not None)
        rect = filled_rect(badge)
        t.ok(f"badge {word} com fundo {hue}", bool(rect and hue_matches(rect[1], hue)), f"fundo={rect[1] if rect else None}")
        ink = text_color(badge) if badge is not None else None
        t.ok(f"texto da badge {word} em branco", is_light(ink, 235), f"cor={ink}")


@case("M-A-07", requirements=["M-05"], level="A",
      task="Criar uma tarefa, marcar e desmarcar o checkbox.",
      expected="O checkbox, à direita da badge e antes do nome, alterna entre marcado e desmarcado.")
def checkbox_toggles(page: Page, t: Checks) -> None:
    need_tasks(page, t, [(TODAY, "MÉDIO", "Tarefa Checkbox")])
    row = row_of(page, "Tarefa Checkbox")
    check = checkbox_in(row)
    t.require("a linha tem um checkbox", check is not None)
    bb, cb, nb = box(badge_in(row, "MÉDIO")), box(check), box(first_visible(row.get_by_text("Tarefa Checkbox", exact=True)))
    t.ok("ordem na linha: badge, checkbox, nome", bool(bb and cb and nb and bb.cx < cb.cx < nb.cx), f"{bb} {cb} {nb}")
    t.ok("começa desmarcado", not check.is_checked())
    t.act("marcar", lambda: check.click(timeout=2000))
    t.ok("fica marcado", check.is_checked())
    t.act("desmarcar", lambda: check.click(timeout=2000))
    t.ok("volta a desmarcado", not check.is_checked())


@case("M-A-08", requirements=["M-06", "M-07"], level="A",
      task="Criar duas tarefas e clicar na lixeira de uma.",
      expected="Cada linha tem lápis e lixeira na extremidade direita; a tarefa excluída some e a outra permanece.")
def delete_task(page: Page, t: Checks) -> None:
    need_tasks(page, t, [(TODAY, "URGENTE", "Tarefa Apagar"), (TODAY, "RELAXA", "Tarefa Manter")])
    row = row_of(page, "Tarefa Apagar")
    actions = row_actions(row)
    t.ok("a linha tem um controle de edição (lápis)", actions["edit"] is not None)
    t.require("a linha tem um controle de exclusão (lixeira)", actions["delete"] is not None)
    rb, eb, db = box(row), box(actions["edit"]), box(actions["delete"])
    t.ok("lápis e lixeira ficam na extremidade direita, o lápis antes da lixeira",
         bool(rb and eb and db and eb.cx < db.cx and db.x1 > rb.x1 - 200), f"{rb} {eb} {db}")
    t.act("clicar na lixeira", lambda: actions["delete"].click(timeout=2000))
    page.wait_for_timeout(250)
    t.ok("a tarefa excluída some da lista", row_of(page, "Tarefa Apagar") is None)
    t.ok("a outra tarefa permanece", row_of(page, "Tarefa Manter") is not None)


@case("M-A-09", requirements=["M-09"], level="A",
      task="Criar 14 tarefas no mesmo dia, mais do que cabem na tela.",
      expected="Só a lista rola: a página não rola, o header e o formulário continuam visíveis.")
def only_the_list_scrolls(page: Page, t: Checks) -> None:
    need_tasks(page, t, [(TODAY, "MÉDIO", f"Item {n:02d}") for n in range(1, 15)])
    t.require("existe um contêiner com rolagem vertical própria", page.evaluate(_SCROLLABLE_JS))  # efeito principal
    page_scrolls = page.evaluate("() => document.scrollingElement.scrollHeight > window.innerHeight + 2")
    t.ok("a página inteira não rola", not page_scrolls)
    last = first_visible(page.get_by_text("Item 14", exact=True))
    if last is not None:
        last.scroll_into_view_if_needed()
    form = find_task_form(page)
    header, add = box(find_text(page, "tarefas para fazer", exact=True)), box(form.add)
    t.ok("o header segue visível no topo", bool(header and header.y >= 0 and header.y1 <= 120), f"{header}")
    t.ok("o formulário de adição segue visível na tela", bool(add and 0 <= add.y1 <= 900), f"{add}")


_SCROLLABLE_JS = """
() => Array.from(document.querySelectorAll('body *')).some((el) => {
  const cs = getComputedStyle(el);
  return /(auto|scroll)/.test(cs.overflowY) && el.scrollHeight > el.clientHeight + 2 && el.clientHeight > 80;
})
"""


@case("M-A-10", requirements=["M-12"], level="A",
      task="Criar uma tarefa URGENTE e uma RELAXA e escolher URGENTE no filtro de prioridade.",
      expected="Só as tarefas URGENTE continuam visíveis.")
def priority_filter(page: Page, t: Checks) -> None:
    need_tasks(page, t, [(TODAY, "URGENTE", "Filtro Urgente"), (TODAY, "RELAXA", "Filtro Relaxa")])
    form = find_task_form(page)
    t.require("existe o filtro de prioridade", form.filter_priority is not None)
    t.act("escolher URGENTE no filtro", lambda: _must(select_priority(form.filter_priority, "URGENTE")))
    commit(form.filter_priority)
    page.wait_for_timeout(250)
    t.require("a tarefa RELAXA fica oculta", row_of(page, "Filtro Relaxa") is None, "o filtro não filtrou")  # efeito principal
    t.ok("a tarefa URGENTE continua visível", row_of(page, "Filtro Urgente") is not None)


@case("M-A-11", requirements=["M-12"], level="A",
      task="Criar tarefas em três dias e filtrar pela data de amanhã.",
      expected="A tarefa da data filtrada continua visível e ao menos uma tarefa de outro dia some (qualquer leitura de 'filtro').")
def date_filter(page: Page, t: Checks) -> None:
    need_tasks(page, t, [(TODAY, "URGENTE", "Dia Hoje"), (TOMORROW, "MÉDIO", "Dia Amanha"), (LATER, "RELAXA", "Dia Depois")])
    form = find_task_form(page)
    t.require("existe o filtro de data", form.filter_date is not None)
    t.act("digitar a data de amanhã no filtro", lambda: _must(fill_date(form.filter_date, TOMORROW)))
    commit(form.filter_date)
    page.wait_for_timeout(300)
    hidden = [d for d in ("Dia Hoje", "Dia Depois") if row_of(page, d) is None]
    t.require("ao menos uma tarefa de outro dia fica oculta", bool(hidden), "nada foi filtrado")  # efeito principal
    t.ok("a tarefa da data filtrada continua visível", row_of(page, "Dia Amanha") is not None)
    t.act("apagar a data do filtro", lambda: _must(clear_date(form.filter_date)))
    commit(form.filter_date)
    page.wait_for_timeout(300)
    t.ok("sem filtro de data, as três tarefas voltam",
         all(row_of(page, d) is not None for d in ("Dia Hoje", "Dia Amanha", "Dia Depois")))


@case("M-A-12", requirements=["M-10", "M-11"], level="A",
      task="Olhar a linha que separa a lista do rodapé.",
      expected="Existe uma linha branca acima do rodapé de criação.")
def footer_divider(page: Page, t: Checks) -> None:
    from oracles.common.probes import horizontal_lines

    form = find_task_form(page)
    desc = box(form.description)
    t.require("existe o rodapé de criação", desc is not None)
    lines = horizontal_lines(page)
    above = [(y, c) for _x, y, _w, c in lines if desc.y - 120 < y < desc.y and c is not None]
    t.ok("há uma linha clara logo acima do rodapé", any(is_light(c, 200) for _y, c in above), f"linhas={above[:4]}")


@case("M-A-13", requirements=["M-08"], level="A", pending="PD-M3",
      task="Clicar no lápis de uma tarefa.",
      expected="A tarefa pode ser editada (o mecanismo não é descrito no prompt: pendente).")
def edit_flow(page: Page, t: Checks) -> None:
    t.pending("a edição altera a tarefa", "PD-M3")
