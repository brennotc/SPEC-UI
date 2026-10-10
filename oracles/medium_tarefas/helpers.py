"""Auxiliares de medium_tarefas: criar tarefas pela UI (PD-M2), achar badge/linha/campos e medir linhas."""

import re
from datetime import date

from playwright.sync_api import Locator, Page

from oracles.common.dates import fill_date
from oracles.common.geometry import box, first_visible
from oracles.common.locators import TaskForm, find_task_form, fold, row_of, select_priority
from specui.oracle import Checks


def add_task(page: Page, due: date, priority: str, description: str) -> bool:
    """Cria uma tarefa preenchendo o rodapé e clicando no +. False se qualquer passo falhar."""
    form = find_task_form(page)
    if not all((form.date, form.priority, form.description, form.add)):
        return False
    try:
        if not fill_date(form.date, due) or not select_priority(form.priority, priority):
            return False
        form.description.fill(description)
        form.add.click(timeout=2000)
        page.wait_for_timeout(200)
        return row_of(page, description) is not None
    except Exception:  # noqa: BLE001
        return False


def need_tasks(page: Page, t: Checks, tasks: list[tuple[date, str, str]]) -> None:
    """Pré-condição: cria as tarefas pela UI; se alguma não aparecer, o caso fica bloqueado (NO)."""
    for due, priority, description in tasks:
        t.require(f"criar a tarefa '{description}' pela interface", add_task(page, due, priority, description),
                  "a tarefa não apareceu na lista")


def badge_in(row: Locator | None, word: str) -> Locator | None:
    if row is None:
        return None
    return first_visible(row.get_by_text(re.compile(rf"^\s*{re.escape(word)}\s*$", re.IGNORECASE)))


def checkbox_in(row: Locator | None) -> Locator | None:
    if row is None:
        return None
    return first_visible(row.get_by_role("checkbox")) or first_visible(row.locator("input[type=checkbox]"))


def option_labels(select: Locator) -> list[str]:
    try:
        return [fold(label) for label in select.locator("option").all_inner_texts()]
    except Exception:  # noqa: BLE001
        return []


def visible_text(page: Page, text: str) -> bool:
    return first_visible(page.get_by_text(text, exact=True)) is not None


def rows_top_to_bottom(page: Page, descriptions: list[str]) -> list[str]:
    boxes = [(b.cy, d) for d in descriptions if (b := box(first_visible(page.get_by_text(d, exact=True)))) is not None]
    return [d for _y, d in sorted(boxes)]


def heading_y(page: Page, pattern: re.Pattern[str] | str, exact: bool = False) -> float | None:
    if isinstance(pattern, re.Pattern):  # já compilado (ex.: heading_pattern): usar como veio
        rx = pattern
    else:
        rx = re.compile(rf"^\s*{pattern}\s*$" if exact else pattern, re.IGNORECASE)
    node = first_visible(page.get_by_text(rx))
    b = box(node)
    return b.cy if b else None


def form_or_none(page: Page) -> TaskForm:
    return find_task_form(page)


def sorted_left_to_right(*locators: Locator | None) -> bool:
    """Os controles existem e seus centros crescem na ordem dada (esquerda para a direita)."""
    boxes = [box(x) for x in locators]
    return all(b is not None for b in boxes) and [b.cx for b in boxes] == sorted(b.cx for b in boxes)
