"""Adaptadores puros dos oráculos (sem navegador): cores, datas, geometria e texto."""

from datetime import date

import pytest

from oracles.common.colors import (
    delta_e,
    hue_bucket,
    is_dark,
    is_white,
    parse_css_color,
    relative_luminance,
    rgb_to_hsl,
    to_rgb,
)
from oracles.common.dates import LATER, TODAY, TOMORROW, digits, heading_pattern, slashed
from oracles.common.geometry import Box
from oracles.common.locators import fold, minutes_from_value


@pytest.mark.parametrize(
    "value, expected",
    [
        ("rgb(215, 71, 71)", (215, 71, 71, 1.0)),
        ("rgba(10, 20, 30, 0.5)", (10, 20, 30, 0.5)),
        ("rgb(10 20 30 / 50%)", (10, 20, 30, 0.5)),
        ("color(srgb 1 0 0)", (255, 0, 0, 1.0)),
        ("color(srgb 0 0.5 1 / 0.25)", (0, 128, 255, 0.25)),
        ("#E56060", (229, 96, 96, 1.0)),
        ("#fff", (255, 255, 255, 1.0)),
        ("transparent", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_css_color(value, expected):
    assert parse_css_color(value) == expected


@pytest.mark.parametrize(
    "hex_, bucket",
    [
        # as cores nomeadas pelo prompt das 3 tarefas (hex da spec) caem na faixa certa
        ("#D74747", "red"), ("#E56060", "red"), ("#FF0000", "red"), ("#B50000", "red"),
        ("#658B5C", "green"), ("#0F633F", "green"), ("#105610", "green"),
        ("#C5CC9E", "yellow"),  # o "verde claro" do corpo de Aprovado é amarelado: o corpo só se testa por luminância
        ("#5684D9", "blue"), ("#60C2E5", "blue"), ("#0B73B7", "blue"), ("#9EBACC", "blue"),
        ("#8D8A31", "yellow"),  # o "amarelo" da spec é oliva (matiz ~58°)
        ("#B77A0B", "orange"), ("#CCB59E", "orange"),
        ("#440BB7", "purple"), ("#AA9ECC", "purple"),
        ("#D7CFCF", "gray"), ("#656060", "gray"), ("#000000", "gray"), ("#FFFFFF", "gray"),
    ],
)
def test_hue_bucket_matches_the_colors_named_in_the_prompts(hex_, bucket):
    assert hue_bucket(to_rgb(hex_)) == bucket


def test_hue_bucket_edges_and_unknown():
    assert hue_bucket(None) is None
    assert hue_bucket((0, 200, 200)) is None  # ciano: fora de todas as faixas
    assert hue_bucket((255, 0, 20)) == "red"  # matiz ~352: o vermelho dá a volta
    assert 0 <= rgb_to_hsl((255, 0, 0))[0] < 1


def test_luminance_white_and_dark():
    assert relative_luminance((255, 255, 255)) == pytest.approx(1.0)
    assert relative_luminance((0, 0, 0)) == 0.0
    assert is_white((255, 255, 255)) and is_white((240, 240, 240)) and not is_white((200, 200, 200))
    assert is_dark((0, 0, 0)) and not is_dark((128, 128, 128))
    assert not is_white(None) and not is_dark(None)


def test_delta_e():
    assert delta_e((10, 20, 30), (10, 20, 30)) == pytest.approx(0.0, abs=1e-6)
    assert delta_e((0, 0, 0), (255, 255, 255)) == pytest.approx(100.0, abs=0.5)
    assert delta_e((215, 71, 71), (214, 71, 71)) < 5  # a tolerância do nível B
    assert delta_e((215, 71, 71), (101, 139, 92)) > 5


# ---------------------------------------------------------------- datas


def test_the_fixed_today_is_a_tuesday_with_three_distinct_days():
    assert TODAY == date(2026, 3, 10) and TODAY.weekday() == 1
    assert (TOMORROW - TODAY).days == 1 and (LATER - TODAY).days == 3
    assert digits(TODAY) == "10032026" and slashed(LATER) == "13/03/2026"


@pytest.mark.parametrize("text", ["13/03/2026", "13 de março", "13 de Março de 2026", "sex, 13 mar", "2026-03-13", "13/3", "Sexta-feira, 13/03"])
def test_heading_pattern_matches_a_written_day(text):
    assert heading_pattern(LATER).search(text)


@pytest.mark.parametrize("text", ["Hoje", "Amanhã", "10/03/2026", "30/03/2026", "113/03", "13/04/2026", "13/10"])
def test_heading_pattern_rejects_other_days(text):
    assert not heading_pattern(LATER).search(text)


# ---------------------------------------------------------------- geometria e texto


def test_box_relations():
    a, b, c = Box(0, 0, 100, 20), Box(120, 4, 50, 20), Box(0, 40, 100, 20)
    assert a.overlaps_vertically(b) and not a.overlaps_vertically(c)
    assert a.overlaps_horizontally(c) and not a.overlaps_horizontally(b)
    assert (a.cx, a.cy, a.x1, a.y1, a.area) == (50, 10, 100, 20, 2000)
    assert a.contains_point(50, 10) and not a.contains_point(150, 10)


@pytest.mark.parametrize(
    "value, minutes",
    [("25", 25), ("25:00", 25), ("05:00", 5), ("5", 5), ("15", 15), ("1,5", 1.5), ("30:30", 30.5), ("abc", None), ("", None), ("25 min", None)],
)
def test_minutes_from_value_accepts_both_readings_of_the_prompt(value, minutes):
    assert minutes_from_value(value) == minutes


def test_fold_removes_accents_and_case():
    assert fold("MÉDIO") == fold("medio") == "medio"
    assert fold("Amanhã") == "amanha"


def test_researcher_color_decisions_pd_c1_and_pd_c2():
    from oracles.common.colors import hue_bucket, hue_matches

    assert hue_bucket((226, 232, 240)) == "gray"  # PD-C1: cinza-azulado claro é cinza
    assert hue_bucket((197, 204, 158)) != "gray"  # o corpo oliva-claro do Kanban continua colorido
    assert hue_matches((236, 0, 63), "red")  # PD-C2: 344°, a 1° do vermelho
    assert hue_matches((156, 148, 201), "purple")  # lilás a 249°, a 2° do roxo
    assert not hue_matches((250, 245, 255), "purple")  # quase branco não é roxo (é cinza)
    assert not hue_matches((254, 154, 0), "yellow")  # âmbar a 36° continua não sendo amarelo
    assert not hue_matches((0, 128, 0), "red") and hue_matches((0, 128, 0), "green")
    assert hue_matches((255, 0, 20), "red")  # dentro da faixa, como antes
