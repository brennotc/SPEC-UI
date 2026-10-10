"""Suítes reais dos oráculos: autoria (lint, rastreabilidade) e robustez contra páginas que NÃO as satisfazem.

Nenhuma página aqui implementa as tarefas. A página vazia e as fixtures de widgets estáticos só garantem
que (1) as suítes carregam e passam no lint, (2) cada requisito testável tem caso, (3) um app ruim vira
NO/PARTIAL e nunca um erro Python da própria suíte (NameError, TypeError, AttributeError...).
A validação de verdade das suítes é o piloto com LLMs e a mutação (README, seção de oráculos)."""

from pathlib import Path

import pytest

from specui.harness import BrowserSession, StaticServer
from specui.oracle import build_traceability, lint_suite, load_suite, run_suite
from specui.oracle.requirements import load_pending, load_requirements

ORACLES = Path(__file__).resolve().parent.parent / "oracles"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "pages"
TASKS = sorted(p.name for p in ORACLES.iterdir() if p.is_dir() and (p / "requirements.yaml").is_file())
STATIC_FIXTURES = {
    "easy_pomodoro": ["widgets_timer.html"],
    "medium_tarefas": ["widgets_form.html"],
    "hard_kanban": ["widgets_columns.html", "widgets_dnd.html"],
}
SUITE_BUGS = ("NameError", "TypeError", "AttributeError", "KeyError", "IndexError", "UnboundLocalError", "ImportError", "SyntaxError")


@pytest.mark.parametrize("task_id", TASKS)
def test_suite_lints_and_traces(task_id):
    suite = load_suite(ORACLES, task_id)
    assert suite.cases, "suíte sem casos"
    assert lint_suite(suite, ORACLES) == []
    requirements = load_requirements(ORACLES, task_id)
    markdown, problems = build_traceability(suite, requirements)
    assert problems == []
    assert task_id in markdown
    pending_ids = {p.id for p in load_pending(ORACLES, task_id)}
    assert {pid for r in requirements for pid in r.pending} <= pending_ids
    assert all(p.status == "decided" or p.rule in (1, 2, 3) for p in load_pending(ORACLES, task_id))


@pytest.mark.parametrize("task_id", TASKS)
def test_every_case_has_unique_id_with_task_prefix(task_id):
    suite = load_suite(ORACLES, task_id)
    ids = [c.id for c in suite.cases]
    assert len(ids) == len(set(ids))
    assert all(c.level in ("A", "B") for c in suite.cases)
    assert all(c.task and c.expected for c in suite.cases), "todo caso descreve Task e Expected Result"


def _run_on(tmp_path, html: str, suite):
    site = tmp_path / "site"
    site.mkdir(exist_ok=True)
    (site / "index.html").write_text(html, encoding="utf-8")
    with StaticServer(site) as server, BrowserSession() as session:
        return run_suite(suite, session, server.url, (1440, 900))


def _assert_no_suite_bugs(outcomes):
    bugs = [(o.case_id, o.error) for o in outcomes if o.error and o.error.startswith(SUITE_BUGS)]
    assert bugs == [], f"erros Python na própria suíte: {bugs}"


@pytest.mark.slow
@pytest.mark.parametrize("task_id", TASKS)
def test_blank_app_is_blocked_not_crashed(task_id, tmp_path):
    suite = load_suite(ORACLES, task_id)
    outcomes = _run_on(tmp_path, "<!doctype html><body><app-root><p>vazio</p></app-root></body>", suite)
    executed = [o for o in outcomes if o.outcome != "PENDING"]
    _assert_no_suite_bugs(outcomes)
    assert executed
    # uma página vazia não pode ganhar nota funcional relevante: no máximo os casos que medem "fundo branco"
    yes = [o.case_id for o in executed if o.outcome == "YES"]
    assert len(yes) <= max(1, len(executed) // 8), f"página vazia passou em {yes}"


@pytest.mark.slow
@pytest.mark.parametrize("task_id,fixture", [(t, f) for t, fs in STATIC_FIXTURES.items() if t in TASKS for f in fs])
def test_static_widgets_do_not_break_the_suite(task_id, fixture, tmp_path):
    suite = load_suite(ORACLES, task_id)
    html = (FIXTURES / fixture).read_text(encoding="utf-8").replace("__BUTTON_NAME__", "Iniciar temporizador").replace("__DATE_TYPE__", "text")
    outcomes = _run_on(tmp_path, html, suite)
    _assert_no_suite_bugs(outcomes)
    assert all(o.n_total >= 0 and o.duration_ms >= 0 for o in outcomes)
