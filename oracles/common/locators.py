"""Adaptadores de localização (AD-*): como achar, na tela, os elementos que o PROMPT descreve.

Regra de justiça entre as condições: só papel (role), rótulo, texto visível e a geometria que o
próprio prompt dá ("abaixo do número", "extremidade direita"). Nunca id, classe nem atributos de teste,
que só a spec revelaria. Os adaptadores NÃO esperam: devolvem None quando não acham, e o caso
registra a asserção como falha. Mecânica de widget (como digitar numa máscara de data, como
arrastar) fica aqui; interpretação de requisito, nunca.
"""

import contextlib
import re
import unicodedata
from dataclasses import dataclass
from itertools import pairwise

from playwright.sync_api import Locator, Page

from oracles.common.colors import RGB, to_rgb, with_rgba
from oracles.common.geometry import Box, box, first_visible, sorted_by_x, visible_all

# ----------------------------------------------------------------------------- texto


def fold(text: str) -> str:
    """Minúsculas e sem acentos: compara 'MÉDIO' com 'Medio'."""
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).lower().strip()


def find_text(page: Page, pattern: str, exact: bool = False) -> Locator | None:
    """Primeiro elemento visível cujo texto casa com `pattern` (regex, sem diferenciar maiúsculas)."""
    rx = re.compile(rf"^\s*(?:{pattern})\s*$" if exact else pattern, re.IGNORECASE)
    return first_visible(page.get_by_text(rx))


def text_of(locator: Locator | None) -> str:
    if locator is None:
        return ""
    try:
        return " ".join(locator.inner_text(timeout=1500).split())
    except Exception:  # noqa: BLE001
        return ""


def icon_on_same_row(page: Page, text: Locator | None) -> Locator | None:
    """Ícone (svg/img) na mesma linha do texto e à ESQUERDA dele (o logo/ícone do header)."""
    tb = box(text)
    if tb is None:
        return None
    for icon in visible_all(page.locator("svg, img")):
        ib = box(icon)
        if ib and ib.overlaps_vertically(tb) and ib.cx < tb.cx:
            return icon
    return None


def audio_plays(page: Page) -> int:
    """Quantas vezes o app chamou `audio.play()` (espião instalado pelo runner)."""
    try:
        return int(page.evaluate("() => (window.__specui ? window.__specui.audioPlays : 0)"))
    except Exception:  # noqa: BLE001
        return 0


# ----------------------------------------------------------------------------- Pomodoro (AD-E1, AD-E2)

MMSS = re.compile(r"^\s*\d{1,2}:\d{2}\s*$")
PLAY_NAME = re.compile(r"iniciar|play|pausar|pause|start|retomar|resume|come[cç]ar|continuar|parar|stop", re.IGNORECASE)


def timer_display(page: Page) -> Locator | None:
    """AD-E2: o visor é o MAIOR elemento visível cujo texto é MM:SS (os inputs de configuração
    também podem mostrar MM:SS, mas são menores)."""
    best, best_area = None, 0.0
    for node in visible_all(page.get_by_text(MMSS), 20):
        b = box(node)
        if b and b.area > best_area:
            best, best_area = node, b.area
    return best


def find_play_button(page: Page, display: Locator | None) -> Locator | None:
    """AD-E1: botão de play/pause pelo nome acessível; senão, o botão visível mais próximo
    ABAIXO do visor (o prompt diz: "abaixo dos números tem um símbolo redondo de play/pause")."""
    named = first_visible(page.get_by_role("button", name=PLAY_NAME))
    if named is not None:
        return named
    db = box(display)
    if db is None:
        return None
    best, best_distance = None, float("inf")
    for button in visible_all(page.get_by_role("button")):
        bb = box(button)
        if bb and bb.cy > db.cy:
            distance = abs(bb.cx - db.cx) + (bb.cy - db.y1) if bb.cy > db.y1 else abs(bb.cx - db.cx) + 1000
            if distance < best_distance:
                best, best_distance = button, distance
    return best


def config_inputs(page: Page, display: Locator | None) -> list[Locator]:
    """Os inputs de tempo, ABAIXO do visor, da esquerda para a direita (Foco Total, Curta, Longa)."""
    db = box(display)
    found = visible_all(page.get_by_role("spinbutton")) + visible_all(page.get_by_role("textbox"))
    below = [i for i in found if (b := box(i)) is not None and (db is None or b.cy > db.y1)]
    return sorted_by_x(below)


def minutes_from_value(value: str) -> float | None:
    """'25' e '25:00' valem 25 min: o prompt admite as duas leituras (PD-E1, regra 1)."""
    value = value.strip()
    if m := re.fullmatch(r"(\d{1,3}):(\d{2})", value):
        return int(m.group(1)) + int(m.group(2)) / 60
    if re.fullmatch(r"\d{1,3}(?:[.,]\d+)?", value):
        return float(value.replace(",", "."))
    return None


def wait_display(page: Page, expected: str, timeout_ms: int = 1500) -> None:
    """Espera (polling) o visor mostrar `expected`. O visor é RE-LOCALIZADO a cada leitura: o índice
    do elemento pode mudar quando o texto muda. Levanta AssertionError no tempo limite."""
    waited = 0
    while True:
        current = text_of(timer_display(page))
        if current == expected:
            return
        if waited >= timeout_ms:
            raise AssertionError(f"visor = {current!r}, esperado {expected!r}")
        page.wait_for_timeout(100)
        waited += 100


def background_at(page: Page, x: float, y: float) -> RGB | None:
    """Fundo EFETIVO do ponto (x, y) da tela: o elemento ali e, subindo, o primeiro fundo opaco."""
    js = with_rgba(r"""
    ([x, y]) => {
      /*RGBA*/
      for (let n = document.elementFromPoint(x, y); n; n = n.parentElement) {
        const bg = toRGBA(getComputedStyle(n).backgroundColor);
        if (alphaOf(bg) > 0.05) return bg;
      }
      // fora da caixa do body (ex.: o ponto cai no <html>): o fundo do body se propaga para a tela inteira
      for (const n of [document.body, document.documentElement]) {
        const bg = toRGBA(getComputedStyle(n).backgroundColor);
        if (alphaOf(bg) > 0.05) return bg;
      }
      return 'rgb(255, 255, 255)';
    }
    """)
    try:
        return to_rgb(page.evaluate(js, [x, y]))
    except Exception:  # noqa: BLE001
        return None


def circle_border_color(display: Locator) -> RGB | None:
    """Cor da borda do círculo que contém o visor: o primeiro ancestral redondo com borda."""
    js = with_rgba(r"""
    (el) => {
      /*RGBA*/
      for (let n = el; n && n !== document.body; n = n.parentElement) {
        const cs = getComputedStyle(n), r = n.getBoundingClientRect();
        const width = parseFloat(cs.borderTopWidth) || 0;
        const radius = parseFloat(cs.borderTopLeftRadius) || 0;
        const round = cs.borderTopLeftRadius.includes('%') ? radius >= 40 : radius >= 0.4 * Math.min(r.width, r.height);
        if (width > 0 && round && r.width > 100) return toRGBA(cs.borderTopColor);
      }
      return null;
    }
    """)
    try:
        return to_rgb(display.evaluate(js, timeout=1500))
    except Exception:  # noqa: BLE001
        return None


# ----------------------------------------------------------------------------- lista de tarefas

PRIORITY_WORDS = {"URGENTE": "red", "MÉDIO": "yellow", "RELAXA": "green"}
_DESC_LABEL = re.compile(r"descri[cç][aã]o da tarefa", re.IGNORECASE)
_ADD_NAME = re.compile(r"adicionar|add|nova|novo|criar|incluir|salvar|\+", re.IGNORECASE)


@dataclass
class TaskForm:
    """Formulário 'Nova tarefa' (rodapé) e filtros (abaixo do header)."""

    description: Locator | None = None
    date: Locator | None = None
    priority: Locator | None = None
    add: Locator | None = None
    filter_date: Locator | None = None
    filter_priority: Locator | None = None


def _visible_inputs(page: Page) -> list[Locator]:
    return visible_all(page.locator("input"))


def _is_date_like(node: Locator) -> bool:
    kind = (node.get_attribute("type") or "text").lower()
    return kind in ("date", "text", "tel", "")


def _selects(page: Page) -> list[Locator]:
    native = visible_all(page.locator("select"))
    return native or visible_all(page.get_by_role("combobox"))


def find_task_form(page: Page) -> TaskForm:
    """AD-M1/M2: localiza o formulário do rodapé e os filtros.

    A descrição é achada pelo rótulo/placeholder "Descrição da tarefa" (o prompt dá esse texto);
    data, prioridade e "+" são os controles da MESMA linha. Os filtros são os controles de data
    e de seleção que ficam ACIMA dessa linha."""
    description = (
        first_visible(page.get_by_label(_DESC_LABEL))
        or first_visible(page.get_by_placeholder(_DESC_LABEL))
        or first_visible(page.get_by_role("textbox", name=re.compile(r"descri", re.IGNORECASE)))
    )
    if description is None:  # sem o rótulo: "um longo input" na parte de baixo da tela
        wide = [(b.w, n) for n in visible_all(page.get_by_role("textbox")) if (b := box(n)) and b.cy > 450 and b.w > 250]
        description = max(wide, key=lambda pair: pair[0])[1] if wide else None
    form = TaskForm(description=description)
    row = box(description)
    if row is None:
        return form

    same_row, above = [], []
    for node in (i for i in _visible_inputs(page) if _is_date_like(i)):
        b = box(node)
        if b is None or (abs(b.x - row.x) < 1 and abs(b.y - row.y) < 1):  # o próprio campo de descrição
            continue
        (same_row if b.overlaps_vertically(row) else above).append(node)
    left_of_description = sorted_by_x([n for n in same_row if (box(n) or row).cx < row.cx])
    form.date = left_of_description[0] if left_of_description else None
    form.filter_date = sorted_by_x(above)[0] if above else None

    selects = _selects(page)
    form_selects = [s for s in selects if (b := box(s)) and b.overlaps_vertically(row)]
    filter_selects = [s for s in selects if s not in form_selects and box(s)]
    form.priority = form_selects[0] if form_selects else None
    form.filter_priority = filter_selects[0] if filter_selects else None

    candidates = visible_all(page.get_by_role("button", name=_ADD_NAME))
    on_row = [c for c in candidates if (b := box(c)) and b.overlaps_vertically(row) and b.cx > row.x1 - 10]
    if not on_row:  # ícone "+" sem nome acessível: o último clicável da linha, à direita do input
        icons = visible_all(page.locator("svg, img, button"))
        on_row = [c for c in icons if (b := box(c)) and b.overlaps_vertically(row) and b.cx > row.x1]
    form.add = sorted_by_x(on_row)[-1] if on_row else None
    return form


def select_priority(select: Locator, word: str) -> bool:
    """Escolhe a prioridade (URGENTE | MÉDIO | RELAXA) num <select> nativo ou combobox customizado."""
    target = fold(word)
    try:
        if select.evaluate("(n) => n.tagName") == "SELECT":
            for label in select.locator("option").all_inner_texts():
                if target in fold(label):
                    select.select_option(label=label)
                    return True
            return False
        select.click()
        option = select.page.get_by_role("option", name=re.compile(re.escape(word), re.IGNORECASE))
        pick = first_visible(option)
        if pick is None:
            return False
        pick.click()
        return True
    except Exception:  # noqa: BLE001
        return False


def commit(locator: Locator) -> None:
    """Dispara `change` e tira o foco (alguns filtros só aplicam ao confirmar a edição)."""
    with contextlib.suppress(Exception):
        locator.evaluate("(n) => { n.dispatchEvent(new Event('change', { bubbles: true })); n.blur(); }")


_ONE_CHECKBOX = "count(.//input[@type='checkbox'] | .//*[@role='checkbox']) = 1"


def row_of(page: Page, description: str) -> Locator | None:
    """Linha da tarefa: o MENOR ancestral do texto com UM checkbox (o desta tarefa) e com botões.

    Um app pode agrupar [badge, checkbox, nome] num bloco e [lápis, lixeira] num bloco irmão: o menor ancestral com
    checkbox seria só a metade esquerda. Exigir também um botão pega a linha inteira; se a linha não tiver nenhum
    botão (ícones clicáveis sem <button>), vale o menor ancestral com o checkbox."""
    text = first_visible(page.get_by_text(description, exact=True))
    if text is None:
        return None
    with_buttons = text.locator(
        f"xpath=ancestor::*[{_ONE_CHECKBOX} and count(.//button[not(@role='checkbox')] | .//*[@role='button']) >= 1][1]"
    )
    if with_buttons.count():
        return with_buttons
    row = text.locator("xpath=ancestor::*[.//input[@type='checkbox'] or .//*[@role='checkbox']][1]")
    return row if row.count() else None


def row_actions(row: Locator | None) -> dict[str, Locator | None]:
    """Lápis (editar) e lixeira (excluir): pelo nome acessível, senão pela posição (o prompt:
    "no final da linha, na extremidade direita, os ícones de lápis e lixeira" nessa ordem)."""
    if row is None:
        return {"edit": None, "delete": None}
    named_delete = first_visible(row.get_by_role("button", name=re.compile(r"exclu|delet|remov|apag|lixeira|trash", re.IGNORECASE)))
    named_edit = first_visible(row.get_by_role("button", name=re.compile(r"edit|l[aá]pis|pencil", re.IGNORECASE)))
    if named_delete is not None or named_edit is not None:
        return {"edit": named_edit, "delete": named_delete}
    clickable = sorted_by_x(visible_all(row.locator("button, [role=button], svg, img, ng-icon")))
    rb = box(row)
    clickable = [c for c in clickable if (b := box(c)) and (rb is None or b.cx > rb.x + rb.w * 0.5)]
    if len(clickable) >= 2:
        return {"edit": clickable[-2], "delete": clickable[-1]}
    return {"edit": None, "delete": clickable[-1] if clickable else None}


# ----------------------------------------------------------------------------- Kanban

COLUMN_TITLES = ("Para Fazer", "Em Progresso", "Feito", "Aprovado")
_ADD_CARD_NAME = re.compile(r"adicionar|add|nov[ao]|criar|\+", re.IGNORECASE)


def column_title_boxes(page: Page) -> list[Box | None]:
    return [box(find_text(page, re.escape(title), exact=True)) for title in COLUMN_TITLES]


def column_ranges(page: Page) -> list[tuple[float, float]] | None:
    """AD-H1: faixas de x de cada coluna = pontos médios entre os centros dos quatro títulos."""
    boxes = column_title_boxes(page)
    if any(b is None for b in boxes):
        return None
    centers = [b.cx for b in boxes if b]
    if centers != sorted(centers):
        return None
    cuts = [(a + b) / 2 for a, b in pairwise(centers)]
    edges = [float("-inf"), *cuts, float("inf")]
    return list(pairwise(edges))


def column_of(ranges: list[tuple[float, float]], b: Box | None) -> int | None:
    if b is None:
        return None
    for index, (lo, hi) in enumerate(ranges):
        if lo <= b.cx < hi:
            return index
    return None


def card_text(page: Page, description: str) -> Locator | None:
    return first_visible(page.get_by_text(description, exact=True))


def card_column(page: Page, ranges: list[tuple[float, float]], description: str) -> int | None:
    return column_of(ranges, box(card_text(page, description)))


def card_container(text: Locator) -> Locator:
    """AD-H3: o menor ancestral do texto que é um <article> ou contém ≥ 2 botões/ícones."""
    return text.locator(
        "xpath=ancestor::*[self::article or count(.//button | .//*[@role='button']) >= 2 or count(.//svg) >= 2][1]"
    )


def card_actions(page: Page, description: str) -> dict[str, Locator | None]:
    """Lápis e lixeira do card (nome acessível; senão posição: lápis, lixeira, na ordem do prompt)."""
    text = card_text(page, description)
    if text is None:
        return {"edit": None, "delete": None}
    container = card_container(text)
    if not container.count():
        return {"edit": None, "delete": None}
    return row_actions(container)


def plus_candidates(page: Page) -> list[Locator]:
    """Controles de adicionar (botão com nome de adicionar/'+', ou o texto '+')."""
    return visible_all(page.get_by_role("button", name=_ADD_CARD_NAME)) + visible_all(page.get_by_text("+", exact=True))


def dashed_boxes(page: Page) -> list[Box]:
    """Caixas dos elementos com contorno tracejado (o card esmaecido de criação)."""
    js = """
    () => Array.from(document.querySelectorAll('*')).filter((el) => {
      const cs = getComputedStyle(el), r = el.getBoundingClientRect();
      return cs.borderTopStyle === 'dashed' && parseFloat(cs.borderTopWidth) > 0 && r.width > 80 && r.height > 60;
    }).map((el) => { const r = el.getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; })
    """
    try:
        return [Box(*raw) for raw in page.evaluate(js)]
    except Exception:  # noqa: BLE001
        return []


def icon_color(locator: Locator | None) -> RGB | None:
    """Cor de um ícone: stroke/fill do svg (ou de seus filhos) com alguma saturação, senão a cor do texto."""
    if locator is None:
        return None
    js = with_rgba(r"""
    (el) => {
      /*RGBA*/
      for (const n of [el, ...el.querySelectorAll('*')]) {
        const cs = getComputedStyle(n);
        for (const v of [cs.stroke, cs.fill, cs.color]) {
          const c = toRGBA(v);
          if (alphaOf(c) <= 0.05) continue;
          const p = c.slice(5, -1).split(',').map(Number);
          if (Math.max(p[0], p[1], p[2]) - Math.min(p[0], p[1], p[2]) > 30) return c;
        }
      }
      return toRGBA(getComputedStyle(el).color);
    }
    """)
    try:
        return to_rgb(locator.evaluate(js, timeout=1500))
    except Exception:  # noqa: BLE001
        return None
