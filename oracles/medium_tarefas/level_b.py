"""Nível B de medium_tarefas: exigências que só a `## Specification` faz (hex, medidas, ordenação, edição, ARIA)."""

import re

from playwright.sync_api import Page

from oracles.common.colors import RGB, computed, computed_color, delta_e, text_color
from oracles.common.dates import LATER, TODAY, TOMORROW, clear_date, fill_date, slashed
from oracles.common.geometry import box, first_visible, visible_all
from oracles.common.locators import (
    commit,
    find_task_form,
    find_text,
    icon_color,
    icon_on_same_row,
    row_actions,
    row_of,
    select_priority,
)
from oracles.common.probes import field_with_value, filled_rect, horizontal_lines
from oracles.medium_tarefas.helpers import (
    badge_in,
    checkbox_in,
    need_tasks,
    option_labels,
    rows_top_to_bottom,
)
from specui.oracle import Checks, case

TOL = 5.0
BLUE, RED, OLIVE, GREEN = (0x60, 0xC2, 0xE5), (0xFF, 0x00, 0x00), (0x8D, 0x8A, 0x31), (0x0F, 0x63, 0x3F)
GRAY = (0xD5, 0xD0, 0xD0)


def _near(actual: RGB | None, expected: RGB) -> bool:
    return actual is not None and delta_e(actual, expected) <= TOL


def _within(value: float | None, target: float, tolerance: float = 2.0) -> bool:
    return value is not None and abs(value - target) <= tolerance


def _px(value: str | None) -> float | None:
    m = re.match(r"-?[\d.]+", value or "")
    return float(m.group()) if m else None


def _must(done: bool) -> None:
    if not done:
        raise ValueError("o controle não aceitou o valor")


@case("M-B-01", requirements=["M-S01"], level="B",
      task="Medir o header.",
      expected="70 px, fundo #60C2E5, ícone e texto pretos.")
def header_spec(page: Page, t: Checks) -> None:
    header = page.locator("header").first
    t.require("existe um <header>", header.count() > 0 and header.is_visible())
    hb = box(header)
    t.ok("altura de 70 px", _within(hb.h if hb else None, 70), f"{hb}")
    bg = filled_rect(header)
    t.ok("fundo #60C2E5 (ΔE ≤ 5)", bool(bg and _near(bg[1], BLUE)), f"fundo={bg[1] if bg else None}")
    title = find_text(page, "tarefas para fazer", exact=True)
    ink = text_color(title)
    t.ok("texto do título preto", ink is not None and max(ink) <= 30, f"cor={ink}")
    icon = icon_on_same_row(page, title)
    icon_ink = computed_color(icon)
    t.ok("ícone preto", icon_ink is not None and max(icon_ink) <= 30, f"cor={icon_ink}")


@case("M-B-02", requirements=["M-S02"], level="B",
      task="Medir os filtros.",
      expected="Rótulos 'Data:' e 'Prioridade:' em cinza a 32 px; campos cinza de 170×55 com texto preto; select com 'Selecione'.")
def filters_spec(page: Page, t: Checks) -> None:
    form = find_task_form(page)
    t.require("existem os dois filtros", form.filter_date is not None and form.filter_priority is not None)
    for name, field in (("data", form.filter_date), ("prioridade", form.filter_priority)):
        rect = filled_rect(field)
        t.ok(f"filtro de {name}: 170 × 55 px", bool(rect and _within(rect[0].w, 170, 3) and _within(rect[0].h, 55, 3)), f"{rect[0] if rect else None}")
        t.ok(f"filtro de {name}: fundo cinza #D5D0D0", bool(rect and _near(rect[1], GRAY)), f"{rect[1] if rect else None}")
        ink = text_color(field)
        t.ok(f"filtro de {name}: texto preto", ink is not None and max(ink) <= 40, f"{ink}")
    for label in (r"data\s*:", r"prioridade\s*:"):
        node = find_text(page, label, exact=True)
        t.ok(f"rótulo '{label}' a 32 px", _within(_px(computed(node, "font-size")) if node else None, 32, 1))
    t.ok("o select de filtro tem 'Selecione' como padrão", "selecione" in (option_labels(form.filter_priority) or [""])[0])


@case("M-B-03", requirements=["M-S04"], level="B",
      task="Criar uma tarefa de cada prioridade e medir as badges.",
      expected="Badges 146×36 com #FF0000, #8D8A31 e #0F633F e texto branco.")
def badges_spec(page: Page, t: Checks) -> None:
    need_tasks(page, t, [(TODAY, "URGENTE", "Hex URGENTE"), (TODAY, "MÉDIO", "Hex MÉDIO"), (TODAY, "RELAXA", "Hex RELAXA")])
    for word, color in (("URGENTE", RED), ("MÉDIO", OLIVE), ("RELAXA", GREEN)):
        badge = badge_in(row_of(page, f"Hex {word}"), word)
        rect = filled_rect(badge)
        t.ok(f"badge {word}: 146 × 36 px", bool(rect and _within(rect[0].w, 146, 3) and _within(rect[0].h, 36, 3)), f"{rect[0] if rect else None}")
        t.ok(f"badge {word}: fundo do mapeamento (ΔE ≤ 5)", bool(rect and _near(rect[1], color)), f"{rect[1] if rect else None}")
        ink = text_color(badge)
        t.ok(f"badge {word}: texto branco", ink is not None and min(ink) >= 240, f"{ink}")


@case("M-B-04", requirements=["M-S03", "M-S15"], level="B",
      task="Criar tarefas em hoje e num dia escrito e medir títulos de grupo e linhas.",
      expected="Título do dia em #60C2E5 a 32 px; linhas brancas de 1327 e 1247 px; data escrita em DD/MM/AAAA.")
def groups_spec(page: Page, t: Checks) -> None:
    need_tasks(page, t, [(TODAY, "URGENTE", "Grupo Hoje"), (LATER, "RELAXA", "Grupo Depois")])
    title = first_visible(page.get_by_text(re.compile(r"^\s*Hoje\s*$", re.IGNORECASE)))
    t.require("existe o título 'Hoje'", title is not None)
    t.ok("título do dia na cor do header (ΔE ≤ 5)", _near(text_color(title), BLUE), f"{text_color(title)}")
    t.ok("título do dia a 32 px", _within(_px(computed(title, "font-size")), 32, 1))
    widths = [w for _x, _y, w, c in horizontal_lines(page) if c is not None and min(c) >= 235]
    t.ok("linha branca de 1327 px (grupo)", any(_within(w, 1327, 6) for w in widths), f"larguras={sorted(widths)[:8]}")
    t.ok("linha branca de 1247 px (tarefa)", any(_within(w, 1247, 6) for w in widths), f"larguras={sorted(widths)[:8]}")
    t.ok("a data do grupo aparece como DD/MM/AAAA", first_visible(page.get_by_text(slashed(LATER))) is not None)


@case("M-B-05", requirements=["M-S05"], level="B",
      task="Marcar a tarefa como concluída.",
      expected="O texto fica tachado e com opacidade reduzida.")
def completed_style(page: Page, t: Checks) -> None:
    need_tasks(page, t, [(TODAY, "MÉDIO", "Concluir esta")])
    row = row_of(page, "Concluir esta")
    name = first_visible(row.get_by_text("Concluir esta", exact=True))
    t.require("existe o checkbox", checkbox_in(row) is not None)
    before = _opacity(name)
    t.act("marcar como concluída", lambda: checkbox_in(row).click(timeout=2000))
    page.wait_for_timeout(250)
    row = row_of(page, "Concluir esta")
    name = first_visible(row.get_by_text("Concluir esta", exact=True)) if row is not None else None
    t.ok("o texto fica tachado", name is not None and _struck(name))
    t.ok("a opacidade fica reduzida", name is not None and _opacity(name) < before - 0.05, f"{before} -> {_opacity(name) if name else None}")


def _struck(locator) -> bool:
    return bool(locator.evaluate(
        "(el) => { for (let n = el; n && n !== document.body; n = n.parentElement) "
        "if (getComputedStyle(n).textDecorationLine.includes('line-through')) return true; return false; }"
    ))


def _opacity(locator) -> float:
    return float(locator.evaluate(
        "(el) => { let o = 1; for (let n = el; n && n !== document.documentElement; n = n.parentElement) "
        "o *= parseFloat(getComputedStyle(n).opacity); return o; }"
    ))


@case("M-B-06", requirements=["M-S06"], level="B",
      task="Olhar as cores dos ícones da linha.",
      expected="Lápis em #60C2E5 e lixeira em #FF0000.")
def icon_colors(page: Page, t: Checks) -> None:
    need_tasks(page, t, [(TODAY, "URGENTE", "Icones")])
    actions = row_actions(row_of(page, "Icones"))
    t.require("a linha tem lápis e lixeira", actions["edit"] is not None and actions["delete"] is not None)
    t.ok("lápis na cor do header (ΔE ≤ 5)", _near(icon_color(actions["edit"]), BLUE), f"{icon_color(actions['edit'])}")
    t.ok("lixeira em vermelho (ΔE ≤ 5)", _near(icon_color(actions["delete"]), RED), f"{icon_color(actions['delete'])}")


@case("M-B-07", requirements=["M-S07"], level="B",
      task="Clicar no lápis, mudar descrição e prioridade e confirmar no check.",
      expected="A linha vira formulário preenchido com check no lugar de lápis/lixeira; ao confirmar, volta com os dados novos.")
def edit_flow_spec(page: Page, t: Checks) -> None:
    need_tasks(page, t, [(TODAY, "URGENTE", "Original")])
    actions = row_actions(row_of(page, "Original"))
    t.require("a linha tem o lápis", actions["edit"] is not None)
    t.act("clicar no lápis", lambda: actions["edit"].click(timeout=2000))
    page.wait_for_timeout(300)
    field = field_with_value(page, "Original")
    t.require("a linha vira formulário com a descrição preenchida", field is not None)
    fb = box(field)
    check = _check_button(page, fb)
    t.ok("existe um ícone de check na linha em edição", check is not None)
    t.ok("lápis e lixeira dão lugar ao check", row_actions(row_of(page, "Original")) == {"edit": None, "delete": None} or _gone(page, fb))
    t.act("mudar a descrição", lambda: field.fill("Editada"))
    t.ok("mudar a prioridade para RELAXA", _edit_priority(page, fb))
    t.act("clicar no check", lambda: check.click(timeout=2000))
    page.wait_for_timeout(300)
    row = row_of(page, "Editada")
    t.ok("a tarefa volta ao modo de exibição com a descrição nova", row is not None)
    t.ok("a descrição antiga some", row_of(page, "Original") is None)
    t.ok("a badge mostra RELAXA", row is not None and badge_in(row, "RELAXA") is not None)


def _check_button(page: Page, near):
    """O botão de confirmação: a MESMA linha do campo em edição, à direita dele."""
    if near is None:
        return None
    named = re.compile(r"check|confirm|salvar|ok|conclu", re.IGNORECASE)
    for button in visible_all(page.get_by_role("button", name=named)):
        b = box(button)
        if b and b.overlaps_vertically(near) and b.cx > near.x1:
            return button
    candidates = [c for c in visible_all(page.locator("button, svg")) if (b := box(c)) and b.overlaps_vertically(near) and b.cx > near.x1]
    return candidates[-1] if candidates else None


def _gone(page: Page, near) -> bool:
    """Não há mais botão de lixeira na linha em edição."""
    named = re.compile(r"exclu|delet|remov|lixeira", re.IGNORECASE)
    return not any((b := box(x)) and near and b.overlaps_vertically(near) for x in visible_all(page.get_by_role("button", name=named)))


def _edit_priority(page: Page, near) -> bool:
    for select in visible_all(page.locator("select")) + visible_all(page.get_by_role("combobox")):
        b = box(select)
        if b and near and b.overlaps_vertically(near):
            return select_priority(select, "RELAXA")
    return False


@case("M-B-08", requirements=["M-S08"], level="B",
      task="Adicionar uma tarefa e olhar o formulário.",
      expected="Os inputs do formulário ficam vazios (prioridade volta ao padrão).")
def form_cleared(page: Page, t: Checks) -> None:
    need_tasks(page, t, [(TODAY, "URGENTE", "Limpar form")])
    form = find_task_form(page)
    t.ok("descrição vazia", form.description.input_value() == "")
    t.ok("data vazia", re.sub(r"\D", "", form.date.input_value()) == "")
    selected = form.priority.evaluate("(n) => n.tagName === 'SELECT' ? n.selectedIndex : 0")
    t.ok("prioridade volta ao item neutro", selected == 0, f"índice={selected}")


@case("M-B-09", requirements=["M-S09"], level="B",
      task="Criar RELAXA, MÉDIO e URGENTE, nessa ordem, no mesmo dia.",
      expected="A lista mostra URGENTE, MÉDIO e RELAXA, de cima para baixo.")
def priority_order(page: Page, t: Checks) -> None:
    need_tasks(page, t, [(TODAY, "RELAXA", "Ordem relaxa"), (TODAY, "MÉDIO", "Ordem medio"), (TODAY, "URGENTE", "Ordem urgente")])
    order = rows_top_to_bottom(page, ["Ordem urgente", "Ordem medio", "Ordem relaxa"])
    t.ok("URGENTE, MÉDIO, RELAXA de cima para baixo", order == ["Ordem urgente", "Ordem medio", "Ordem relaxa"], str(order))


@case("M-B-10", requirements=["M-S10"], level="B",
      task="Filtrar por prioridade e por data e depois limpar os filtros.",
      expected="'Selecione' devolve a lista completa; apagar a data tira o filtro de data.")
def filters_reset(page: Page, t: Checks) -> None:
    need_tasks(page, t, [(TODAY, "URGENTE", "Reset U"), (TOMORROW, "RELAXA", "Reset R")])
    form = find_task_form(page)
    t.require("existem os dois filtros", form.filter_priority is not None and form.filter_date is not None)
    t.act("filtrar por URGENTE", lambda: _must(select_priority(form.filter_priority, "URGENTE")))
    page.wait_for_timeout(250)
    t.ok("a tarefa RELAXA some", row_of(page, "Reset R") is None)
    t.ok("o filtro tem o item neutro 'Selecione'", any("selecione" in x for x in option_labels(form.filter_priority)))
    t.act("voltar para 'Selecione'", lambda: _must(select_priority(form.filter_priority, "Selecione")))
    page.wait_for_timeout(250)
    t.ok("sem filtro de prioridade a lista completa volta", row_of(page, "Reset U") is not None and row_of(page, "Reset R") is not None)
    t.act("filtrar pela data de hoje", lambda: _must(fill_date(form.filter_date, TODAY)))
    commit(form.filter_date)
    page.wait_for_timeout(250)
    t.act("apagar a data do filtro", lambda: _must(clear_date(form.filter_date)))
    commit(form.filter_date)
    page.wait_for_timeout(250)
    t.ok("apagar a data restaura a lista", row_of(page, "Reset U") is not None and row_of(page, "Reset R") is not None)


@case("M-B-11", requirements=["M-S11", "M-S12"], level="B",
      task="Inspecionar nomes acessíveis.",
      expected="Lápis, lixeira e + têm aria-label; filtros e campos do formulário têm label ou aria-label.")
def accessible_names(page: Page, t: Checks) -> None:
    need_tasks(page, t, [(TODAY, "URGENTE", "Nomes")])
    row = row_of(page, "Nomes")
    t.ok("botão de editar com nome acessível", first_visible(row.get_by_role("button", name=re.compile(r"edit", re.IGNORECASE))) is not None)
    t.ok("botão de excluir com nome acessível", first_visible(row.get_by_role("button", name=re.compile(r"exclu|delet|remov", re.IGNORECASE))) is not None)
    t.ok("botão de adicionar com nome acessível", first_visible(page.get_by_role("button", name=re.compile(r"adicion|add|nova", re.IGNORECASE))) is not None)
    unnamed = page.evaluate(
        "() => Array.from(document.querySelectorAll('input:not([type=checkbox]), select')).filter((n) => n.offsetParent !== null)"
        ".filter((n) => !(n.labels && n.labels.length) && !n.getAttribute('aria-label') && !n.getAttribute('aria-labelledby')).length"
    )
    t.ok("todo input/select tem label ou aria-label", unnamed == 0, f"sem nome={unnamed}")


@case("M-B-12", requirements=["M-S13"], level="B",
      task="Inspecionar a estrutura da página.",
      expected="Existem <header>, <main>, <section> e <footer> (ou <form>).")
def semantics(page: Page, t: Checks) -> None:
    for tag in ("header", "main", "section"):
        t.ok(f"existe <{tag}>", page.locator(tag).count() >= 1)
    t.ok("existe <footer> ou <form>", page.locator("footer").count() + page.locator("form").count() >= 1)


@case("M-B-13", requirements=["M-S14"], level="B",
      task="Navegar por Tab pelos campos e botões.",
      expected="Cada tipo de controle focado mostra um anel de foco visível.")
def focus_rings(page: Page, t: Checks) -> None:
    need_tasks(page, t, [(TODAY, "URGENTE", "Foco")])
    page.mouse.click(5, 5)
    rings: dict[str, list[bool]] = {}
    for _ in range(40):
        page.keyboard.press("Tab")
        info = page.evaluate(
            "() => { const n = document.activeElement; if (!n || n === document.body) return null; const cs = getComputedStyle(n);"
            " const kind = n.tagName === 'INPUT' ? (n.type === 'checkbox' ? 'checkbox' : 'input') : n.tagName.toLowerCase();"
            " const ring = (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0) || (cs.boxShadow && cs.boxShadow !== 'none');"
            " return [kind, !!ring]; }"
        )
        if info:
            rings.setdefault(info[0], []).append(info[1])
    t.require("a navegação por Tab alcança controles", bool(rings))
    for kind in ("input", "select", "button", "checkbox"):
        if kind in rings:
            t.ok(f"controles do tipo '{kind}' mostram anel de foco", all(rings[kind]), f"{rings[kind]}")


@case("M-B-14", requirements=["M-S16"], level="B",
      task="Medir o rodapé.",
      expected="Linha cinza acima, campos cinza #D5D0D0 e + azul do header na extremidade direita.")
def footer_spec(page: Page, t: Checks) -> None:
    form = find_task_form(page)
    t.require("existe o formulário do rodapé", all((form.date, form.priority, form.description, form.add)))
    for name, field in (("data", form.date), ("prioridade", form.priority), ("descrição", form.description)):
        rect = filled_rect(field)
        t.ok(f"campo de {name} cinza #D5D0D0", bool(rect and _near(rect[1], GRAY)), f"{rect[1] if rect else None}")
    t.ok("o + usa o azul do header", _near(icon_color(form.add), BLUE), f"{icon_color(form.add)}")
    desc = box(form.description)
    lines = [(y, c) for _x, y, _w, c in horizontal_lines(page) if c and desc and desc.y - 120 < y < desc.y]
    t.ok("há uma linha cinza acima do rodapé", any(c is not None and max(c) - min(c) <= 30 and 90 < sum(c) / 3 < 250 for _y, c in lines), f"{lines[:4]}")
    label = find_text(page, r"nova\s+tarefa\s*:?", exact=True)
    t.ok("'Nova tarefa:' fica à esquerda", bool(box(label) and box(label).x < 300))
    t.ok("o ícone + está na extremidade direita", bool(box(form.add) and box(form.add).x1 > 1300))
