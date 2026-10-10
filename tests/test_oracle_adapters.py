"""Adaptadores contra o Chromium real, usando páginas de fixture GENÉRICAS (nenhuma implementa as
tarefas): só garantem que os adaptadores acham e operam os widgets. pytest -m slow"""

from itertools import pairwise

import pytest

from oracles.common.colors import effective_background, hue_bucket, text_color
from oracles.common.dates import LATER, TODAY, fill_date
from oracles.common.dnd import STRATEGIES, DndDriver
from oracles.common.geometry import box
from oracles.common.locators import (
    background_at,
    card_actions,
    card_column,
    card_container,
    circle_border_color,
    column_of,
    column_ranges,
    commit,
    config_inputs,
    dashed_boxes,
    find_play_button,
    find_task_form,
    find_text,
    icon_color,
    icon_on_same_row,
    minutes_from_value,
    plus_candidates,
    row_actions,
    row_of,
    select_priority,
    text_of,
    timer_display,
    wait_display,
)
from specui.harness import BrowserSession, StaticServer

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def session():
    with BrowserSession() as s:
        yield s


@pytest.fixture
def open_fixture(session, tmp_path, repo_root):
    contexts, servers = [], []

    def _open(name: str, **replacements: str):
        html = (repo_root / "tests" / "fixtures" / "pages" / name).read_text(encoding="utf-8")
        for key, value in replacements.items():
            html = html.replace(f"__{key}__", value)
        (tmp_path / "index.html").write_text(html, encoding="utf-8")
        server = StaticServer(tmp_path).start()
        servers.append(server)
        context = session.new_context((1440, 900))
        contexts.append(context)
        page = context.new_page()
        page.set_default_timeout(3000)
        page.goto(server.url)
        return page

    yield _open
    for context in contexts:
        context.close()
    for server in servers:
        server.stop()


# ---------------------------------------------------------------- timer


def test_timer_display_is_the_biggest_mmss_text(open_fixture):
    page = open_fixture("widgets_timer.html", BUTTON_NAME="Iniciar temporizador")
    display = timer_display(page)
    assert text_of(display) == "25:00"
    assert box(display).area > 20_000  # o visor de 128px, não os inputs de configuração


def test_play_button_found_by_accessible_name_and_by_position(open_fixture):
    page = open_fixture("widgets_timer.html", BUTTON_NAME="Pausar temporizador")
    assert find_play_button(page, timer_display(page)).get_attribute("aria-label") == "Pausar temporizador"
    page = open_fixture("widgets_timer.html", BUTTON_NAME="")  # sem nome: cai na posição (abaixo do visor)
    button = find_play_button(page, timer_display(page))
    assert button is not None and box(button).cy > box(timer_display(page)).cy


def test_config_inputs_are_ordered_left_to_right_and_both_formats_parse(open_fixture):
    page = open_fixture("widgets_timer.html", BUTTON_NAME="x")
    inputs = config_inputs(page, timer_display(page))
    assert [i.input_value() for i in inputs] == ["25", "05:00", "15"]
    assert [minutes_from_value(i.input_value()) for i in inputs] == [25, 5, 15]
    assert config_inputs(page, None) and len(config_inputs(page, None)) == 3


def test_circle_border_and_header_icon(open_fixture):
    page = open_fixture("widgets_timer.html", BUTTON_NAME="x")
    assert hue_bucket(circle_border_color(timer_display(page))) == "red"
    title = find_text(page, "Pomodoro", exact=True)
    icon = icon_on_same_row(page, title)
    assert icon is not None and box(icon).cx < box(title).cx
    assert icon_on_same_row(page, None) is None


# ---------------------------------------------------------------- formulário e lista


@pytest.mark.parametrize("date_type", ["text", "date"])
def test_task_form_is_found_with_filters_above_the_footer(open_fixture, date_type):
    page = open_fixture("widgets_form.html", DATE_TYPE=date_type)
    form = find_task_form(page)
    for name in ("description", "date", "priority", "add", "filter_date", "filter_priority"):
        assert getattr(form, name) is not None, name
    assert form.add.get_attribute("aria-label") == "Adicionar tarefa"
    footer_y = box(form.description).cy
    assert box(form.filter_date).cy < footer_y and box(form.filter_priority).cy < footer_y
    assert abs(box(form.date).cy - footer_y) < 20 and box(form.date).cx < box(form.description).cx
    assert form.filter_date.get_attribute("type") == "text"  # o filtro é o campo de CIMA, não o do formulário


def test_fill_date_for_masked_text_and_native_date(open_fixture):
    page = open_fixture("widgets_form.html", DATE_TYPE="text")
    form = find_task_form(page)
    assert fill_date(form.date, TODAY) and form.date.input_value() == "10032026"
    page = open_fixture("widgets_form.html", DATE_TYPE="date")
    form = find_task_form(page)
    assert fill_date(form.date, LATER) and form.date.input_value() == "2026-03-13"


def test_select_priority_ignores_case_and_accents(open_fixture):
    page = open_fixture("widgets_form.html", DATE_TYPE="text")
    form = find_task_form(page)
    assert select_priority(form.priority, "MÉDIO") and form.priority.evaluate("n => n.selectedOptions[0].text") == "MÉDIO"
    assert select_priority(form.priority, "medio")
    assert select_priority(form.priority, "RELAXA") and form.priority.evaluate("n => n.value") == "RELAXA"
    assert not select_priority(form.priority, "INEXISTENTE")
    assert select_priority(form.filter_priority, "URGENTE")  # o filtro de cima é outro select
    assert form.priority.evaluate("n => n.value") == "RELAXA"
    commit(form.filter_priority)


def test_row_of_and_row_actions_by_name_and_by_position(open_fixture):
    page = open_fixture("widgets_form.html", DATE_TYPE="text")
    named = row_actions(row_of(page, "Lavar a louça"))
    assert named["edit"].get_attribute("aria-label") == "Editar tarefa"
    assert named["delete"].get_attribute("aria-label") == "Excluir tarefa"
    unnamed = row_actions(row_of(page, "Fazer mercado"))  # ícones svg sem nome: lápis, depois lixeira
    assert box(unnamed["edit"]).cx < box(unnamed["delete"]).cx
    assert hue_bucket(icon_color(unnamed["delete"])) == "red"
    assert row_of(page, "tarefa que não existe") is None
    assert page.get_by_text("Lavar a louça").count() == 1


# ---------------------------------------------------------------- kanban


def test_columns_cards_and_placeholder(open_fixture):
    page = open_fixture("widgets_columns.html")
    ranges = column_ranges(page)
    assert ranges is not None and len(ranges) == 4
    assert all(a[1] == b[0] for a, b in pairwise(ranges))  # faixas contíguas
    assert card_column(page, ranges, "Card A") == 0 and card_column(page, ranges, "Card B") == 1
    assert card_column(page, ranges, "Card Z") is None
    plus = plus_candidates(page)
    assert [column_of(ranges, box(p)) for p in plus] == [0]  # um "+", e só na coluna 1
    dashed = dashed_boxes(page)
    assert len(dashed) == 1 and column_of(ranges, dashed[0]) == 0


def test_card_container_and_actions(open_fixture):
    page = open_fixture("widgets_columns.html")
    assert card_container(page.get_by_text("Card A")).evaluate("n => n.tagName") == "ARTICLE"
    named = card_actions(page, "Card A")
    assert hue_bucket(icon_color(named["edit"])) == "blue" and hue_bucket(icon_color(named["delete"])) == "red"
    unnamed = card_actions(page, "Card B")  # ícones svg sem nome
    assert hue_bucket(icon_color(unnamed["edit"])) == "blue" and hue_bucket(icon_color(unnamed["delete"])) == "red"
    assert card_actions(page, "Card Z") == {"edit": None, "delete": None}


def test_column_ranges_none_when_a_title_is_missing(open_fixture):
    page = open_fixture("widgets_columns.html")
    page.evaluate("() => Array.from(document.querySelectorAll('h2')).find((h) => h.textContent === 'Feito').remove()")
    assert column_ranges(page) is None


# ---------------------------------------------------------------- arrastar e soltar


@pytest.mark.parametrize("mode, draggable", [("html5", 'draggable="true"'), ("pointer", "")])
def test_dnd_driver_moves_with_either_implementation(open_fixture, mode, draggable):
    page = open_fixture("widgets_dnd.html", MODE=mode, DRAGGABLE=draggable)
    parent = lambda: page.evaluate("document.getElementById('it').parentElement.id")
    z1, z2 = box(page.locator("#z1")), box(page.locator("#z2"))
    item = page.get_by_text("ITEM", exact=True)
    driver = DndDriver(page)
    assert driver.strategy is None
    assert driver.move_until(item, (z2.cx, z2.cy), lambda: parent() == "z2")
    assert driver.strategy in STRATEGIES and parent() == "z2"
    # volta com a estratégia já validada
    assert driver.drag(page.get_by_text("ITEM", exact=True), (z1.cx, z1.cy)) and parent() == "z1"
    # soltar fora de qualquer zona não move
    assert driver.drag(page.get_by_text("ITEM", exact=True), (5, 880)) and parent() == "z1"


def test_dnd_driver_reports_failure_when_nothing_moves(open_fixture):
    page = open_fixture("widgets_dnd.html", MODE="pointer", DRAGGABLE="")
    item = page.get_by_text("ITEM", exact=True)
    assert not DndDriver(page).move_until(item, (5, 880), lambda: False)  # destino sem zona: nenhuma estratégia move

# ---------------------------------------------------------------- leitura de cores no navegador


def test_background_and_text_colors_are_read_from_the_page(open_fixture):
    page = open_fixture("widgets_columns.html")
    assert background_at(page, 5, 400) == (215, 207, 207)  # fundo da página (#D7CFCF)
    header = find_text(page, "Kanban", exact=True)
    assert effective_background(header) == (16, 86, 16)  # #105610: sobe pelos ancestrais
    ranges = column_ranges(page)
    title = find_text(page, "Em Progresso", exact=True)
    tb = box(title)
    assert background_at(page, tb.cx, tb.cy) == (183, 122, 11)  # cabeçalho laranja (#B77A0B)
    assert background_at(page, tb.cx, tb.y1 + 150) == (204, 181, 158)  # corpo da coluna (#CCB59E)
    assert background_at(page, tb.cx, 800) == (215, 207, 207)  # abaixo do conteúdo: o fundo do body se propaga
    assert text_color(title) == (255, 255, 255) and ranges is not None


def test_wait_display_polls_and_times_out(open_fixture):
    page = open_fixture("widgets_timer.html", BUTTON_NAME="x")
    wait_display(page, "25:00")
    page.evaluate(
        "() => setTimeout(() => { Array.from(document.querySelectorAll('div')).find((d) => d.textContent === '25:00').textContent = '24:59'; }, 300)"
    )
    wait_display(page, "24:59")  # espera o texto mudar (re-localizando o visor)
    with pytest.raises(AssertionError, match=r"visor = '24:59', esperado '10:00'"):
        wait_display(page, "10:00", timeout_ms=300)


def test_colors_in_oklch_and_oklab_are_read_as_srgb(session, tmp_path):
    """O Tailwind 4 calcula as cores em oklch/oklab: os leitores precisam devolver sRGB, não None."""
    from oracles.common.colors import computed_color, effective_background
    from specui.harness.browser import _js

    html = """<!doctype html><body style="margin:0;background:oklch(0.85 0 0)"><app-root>
    <header style="height:70px;background:oklch(0.63 0.2 25)"><svg width="20" height="20"><rect width="20" height="20" style="fill:oklab(0.6 -0.15 0.12)"/></svg>
    <span style="color:oklch(1 0 0)">Titulo</span></header><p style="color:oklab(0.5 -0.05 -0.15 / 0.9)">azul</p></app-root></body>"""
    (tmp_path / "index.html").write_text(html, encoding="utf-8")
    with StaticServer(tmp_path) as server:
        context = session.new_context((1440, 900))
        page = context.new_page()
        page.goto(server.url)
        assert hue_bucket(background_at(page, 720, 30)) == "red"
        assert hue_bucket(icon_color(page.locator("svg"))) == "green"
        assert computed_color(page.get_by_text("Titulo")) == (255, 255, 255)
        assert hue_bucket(text_color(page.get_by_text("azul"))) == "blue"
        assert hue_bucket(effective_background(page.get_by_text("Titulo"))) == "red"
        gray = background_at(page, 720, 600)  # abaixo do conteúdo: o fundo oklch do body
        assert gray is not None and hue_bucket(gray) == "gray" and 200 < gray[0] < 225
        blocks = page.evaluate(_js("dom_blocks.js"))
        colors = {b["text"]: b["color"] for b in blocks}
        assert colors["Titulo"] == [255, 255, 255] and hue_bucket(tuple(colors["azul"])) == "blue"
        context.close()
