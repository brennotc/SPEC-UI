"""Um app INERTE (os controles existem mas não fazem nada) tem de dar NO nos casos cujo efeito principal é pré-condição,
nunca PARTIAL: antes do protocolo de passos, ações e invariantes vacuosos davam 0,5 a uma feature totalmente quebrada
(revisão S2/S3/S4). Navegador real; pytest -m slow."""

from pathlib import Path

import pytest

from specui.harness import BrowserSession, StaticServer
from specui.oracle import load_suite, run_case

pytestmark = pytest.mark.slow

ORACLES = Path(__file__).resolve().parent.parent / "oracles"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "pages"

# (tarefa, página estática inerte, casos que precisam dar NO nela)
INERT = [
    ("easy_pomodoro", "widgets_timer.html", ["E-A-05", "E-A-08", "E-A-09"]),
    ("medium_tarefas", "widgets_form.html", ["M-A-04", "M-A-09", "M-A-10", "M-A-11"]),
]


def _html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8").replace("__BUTTON_NAME__", "Iniciar temporizador").replace("__DATE_TYPE__", "text")


@pytest.mark.parametrize("task_id,fixture,cases", INERT)
def test_inert_app_gets_no_not_partial(task_id, fixture, cases, tmp_path):
    (tmp_path / "index.html").write_text(_html(fixture), encoding="utf-8")
    suite = load_suite(ORACLES, task_id)
    specs = {c.id: c for c in suite.cases}
    with StaticServer(tmp_path) as server, BrowserSession() as session:
        outcomes = {cid: run_case(specs[cid], session, server.url, (1440, 900)) for cid in cases}
    assert {cid: o.outcome for cid, o in outcomes.items()} == dict.fromkeys(cases, "NO"), {
        cid: (o.outcome, o.failed) for cid, o in outcomes.items()}
