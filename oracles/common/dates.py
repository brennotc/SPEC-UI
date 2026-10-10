"""Datas: o 'hoje' do experimento e como preencher campos de data (AD-M1).

O relógio é instalado em 10/03/2026 10:00 (uma terça-feira), então "Hoje" é 10/03, "Amanhã" é 11/03.
"""

import re
from datetime import date, timedelta

from playwright.sync_api import Locator

TODAY = date(2026, 3, 10)
TOMORROW = TODAY + timedelta(days=1)
LATER = TODAY + timedelta(days=3)  # 13/03: um dia "escrito" (nem Hoje nem Amanhã)

_MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def digits(d: date) -> str:
    """DDMMAAAA, para digitar numa máscara."""
    return d.strftime("%d%m%Y")


def slashed(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def heading_pattern(d: date) -> re.Pattern[str]:
    """Casa um título de grupo que cita o dia e o mês de `d` (o prompt só diz "os dias escritos"):
    '13/03/2026', '13 de março', 'sex, 13 mar', '2026-03-13'..."""
    day, month = d.day, d.month
    name = _MONTHS[month - 1]
    return re.compile(
        rf"(?<!\d)0?{day}(?!\d)\D{{0,12}}(?:0?{month}(?!\d)|{name})|{d.isoformat()}", re.IGNORECASE
    )


def _digits_of(value: str) -> str:
    return re.sub(r"\D", "", value)


def fill_date(locator: Locator, d: date) -> bool:
    """Preenche um campo de data, qualquer que seja o widget (AD-M1, mecânica, não requisito):

    1. `type=date`            -> ISO (AAAA-MM-DD);
    2. campo de texto/máscara -> digita DDMMAAAA; se a máscara não aceitar, tenta DD/MM/AAAA.
    Devolve True se o valor final contém os dígitos da data."""
    try:
        if (locator.get_attribute("type") or "").lower() == "date":
            locator.fill(d.isoformat())
            return _digits_of(locator.input_value()) == _digits_of(d.isoformat())
        locator.click()
        locator.fill("")
        locator.press_sequentially(digits(d), delay=15)
        if _digits_of(locator.input_value()) == digits(d):
            return True
        locator.fill(slashed(d))
        return _digits_of(locator.input_value()) == digits(d)
    except Exception:  # noqa: BLE001 - widget que não aceita nenhuma das formas
        return False


def clear_date(locator: Locator) -> bool:
    """Apaga o campo de data (o prompt só descreve o filtro como 'um input com máscara')."""
    try:
        locator.fill("")
        return True
    except Exception:  # noqa: BLE001
        try:
            locator.click()
            locator.press("Control+A")
            locator.press("Backspace")
            return True
        except Exception:  # noqa: BLE001
            return False
