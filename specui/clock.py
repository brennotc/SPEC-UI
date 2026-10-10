"""O relógio fixo do experimento: UMA fonte para o render, o runner dos oráculos e os próprios oráculos.

Terça-feira, 10/03/2026, 10:00 (hora local do contexto do navegador): "Hoje" é 10/03 e "Amanhã" é 11/03, sem virada de dia
durante um caso. Os oráculos foram escritos para esta data (criam tarefas para hoje, amanhã e daqui a 3 dias), então o valor
é parte do instrumento: mudá-lo exige nova versão do oráculo, e `RunConfig` recusa qualquer outro `clock_epoch_iso`.
"""

from datetime import date, datetime, timedelta

FIXED_NOW = "2026-03-10T10:00:00"


def fixed_datetime() -> datetime:
    return datetime.fromisoformat(FIXED_NOW)


def fixed_date() -> date:
    return fixed_datetime().date()


def fixed_plus(minutes: int = 0) -> str:
    """Instante ISO `minutes` depois do relógio fixo (ex.: o ponto em que o oráculo congela o relógio)."""
    return (fixed_datetime() + timedelta(minutes=minutes)).isoformat(timespec="seconds")


def fixed_date_br() -> str:
    """DD/MM/AAAA, para mensagens."""
    return fixed_date().strftime("%d/%m/%Y")
