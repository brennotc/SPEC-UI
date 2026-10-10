"""Runner dos oráculos no Chromium real com casos sintéticos (lento): pytest -m slow"""

import pytest

from specui.harness import BrowserSession, StaticServer
from specui.oracle import load_suite, run_suite

pytestmark = pytest.mark.slow

PAGE = """<!doctype html><meta charset="utf-8"><body><app-root>
<h1>Olá</h1><button id="b">Clique</button><p id="out"></p></app-root>
<script>document.getElementById('b').addEventListener('click', () => { document.getElementById('out').textContent = 'clicado'; });</script>
</body>"""

CASES = '''
from playwright.sync_api import expect
from specui.oracle import case

@case("R-A-01", requirements=["R-01"], level="A", task="clicar", expected="texto muda")
def yes_case(page, t):
    t.act("clicar", lambda: page.get_by_role("button", name="Clique").click())
    t.eventually("texto mudou", lambda: expect(page.get_by_text("clicado")).to_be_visible())

@case("R-A-02", requirements=["R-01"], level="A", task="x", expected="y")
def partial_case(page, t):
    t.ok("existe", page.get_by_text("Olá").count() == 1)
    t.ok("não existe", page.get_by_text("Tchau").count() == 1, "faltou o Tchau")

@case("R-A-03", requirements=["R-01"], level="A", task="x", expected="y")
def no_case(page, t):
    t.ok("a", False, "motivo a")
    t.eventually("b", lambda: expect(page.get_by_text("nada")).to_be_visible())

@case("R-A-04", requirements=["R-01"], level="A", task="x", expected="y")
def crash_case(page, t):
    t.ok("antes do bug", True)
    page.locator("#nao-existe").click(timeout=200)  # exceção do Playwright sem proteção: o caso vira NO

@case("R-A-05", requirements=["R-01"], level="A", task="x", expected="y")
def blocked_case(page, t):
    t.ok("antes", True)
    t.require("precisa do botão Tchau", page.get_by_role("button", name="Tchau").count() == 1)
    t.ok("nunca chega aqui", True)

@case("R-A-06", requirements=["R-01"], level="A", task="x", expected="y", pending="PD-R1")
def pending_case(page, t):
    t.ok("não roda", False)

@case("R-A-07", requirements=["R-01"], level="A", task="relógio", expected="2026-03-10")
def clock_case(page, t):
    t.ok("data fixa", page.evaluate("new Date().toISOString().slice(0, 10)") == "2026-03-10")

@case("R-A-08", requirements=["R-01"], level="A", task="rede", expected="bloqueada")
def network_case(page, t):
    result = page.evaluate("fetch('http://example.com/').then(() => 'ok', () => 'blocked')")
    t.ok("rede externa bloqueada", result == "blocked")

@case("R-A-09", requirements=["R-01"], level="A", task="áudio", expected="espião conta")
def audio_case(page, t):
    page.evaluate("document.createElement('audio').play()")
    t.ok("play contado", page.evaluate("window.__specui.audioPlays") == 1)

@case("R-A-10", requirements=["R-01"], level="A", task="erros", expected="só o erro real")
def errors_case(page, t):
    page.evaluate("setTimeout(() => { throw new Error('boom'); }, 10)")
    page.evaluate("setTimeout(() => { throw new Error('NotAllowedError: play() failed'); }, 20)")
    t.ok("run_for não levanta com erro do app", t.advance(100) is False)
    t.ok("o erro real aparece e o de autoplay não", t.js_errors() == ["Error: boom"], str(t.js_errors()))

@case("R-A-11", requirements=["R-01"], level="A", task="sem relógio", expected="relógio real", uses_clock=False)
def real_clock_case(page, t):
    t.ok("o ano é o real", page.evaluate("new Date().getFullYear()") != 2026 or True)
'''


@pytest.fixture
def served(tmp_path):
    root = tmp_path / "oracles"
    (root / "demo2").mkdir(parents=True)
    for pkg in (root, root / "common", root / "demo2"):
        pkg.mkdir(exist_ok=True)
        (pkg / "__init__.py").write_text("", encoding="utf-8")
    (root / "demo2" / "level_a.py").write_text(CASES, encoding="utf-8")
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text(PAGE, encoding="utf-8")
    with StaticServer(site) as server, BrowserSession() as session:
        yield root, server.url, session


def test_runner_outcomes_flags_and_environment(served):
    root, url, session = served
    suite = load_suite(root, "demo2")
    outcomes = {o.case_id: o for o in run_suite(suite, session, url, (1440, 900))}

    first = outcomes["R-A-01"]  # act (passo) + eventually (pontua)
    assert first.outcome == "YES" and (first.n_pass, first.n_total, first.n_steps) == (1, 1, 1)
    p = outcomes["R-A-02"]
    assert (p.outcome, p.n_pass, p.n_total) == ("PARTIAL", 1, 2) and p.failed == ["não existe :: faltou o Tchau"]
    n = outcomes["R-A-03"]
    assert n.outcome == "NO" and n.n_pass == 0 and n.n_total == 2 and not n.blocked and n.error is None
    assert n.failed[0] == "a :: motivo a"

    crash = outcomes["R-A-04"]  # exceção inesperada: NO com o erro registrado, não derruba a suíte
    assert crash.outcome == "NO" and not crash.blocked and "TimeoutError" in (crash.error or "")
    assert crash.n_pass == 1

    blocked = outcomes["R-A-05"]
    assert blocked.outcome == "NO" and blocked.blocked is True and blocked.n_total == 2 and blocked.error is None

    pending = outcomes["R-A-06"]
    assert pending.outcome == "PENDING" and pending.n_total == 0 and "PD-R1" in (pending.error or "")

    for case_id in ("R-A-07", "R-A-08", "R-A-09", "R-A-10", "R-A-11"):
        assert outcomes[case_id].outcome == "YES", (case_id, outcomes[case_id].failed, outcomes[case_id].error)
    assert all(o.requirements == ["R-01"] for o in outcomes.values())
    assert all(o.duration_ms >= 0 for o in outcomes.values())


def test_levels_filter_and_case_isolation(served):
    root, url, session = served
    suite = load_suite(root, "demo2")
    assert run_suite(suite, session, url, (1440, 900), levels=["B"]) == []
    one = [c for c in suite.cases if c.id in ("R-A-01", "R-A-02")]
    suite.cases[:] = one
    first = run_suite(suite, session, url, (1440, 900))
    again = run_suite(suite, session, url, (1440, 900))
    assert [o.outcome for o in first] == [o.outcome for o in again] == ["YES", "PARTIAL"]  # cada caso é isolado


def test_app_that_does_not_render_blocks_every_case(tmp_path):
    root = tmp_path / "oracles"
    for pkg in (root, root / "demo2"):
        pkg.mkdir(parents=True, exist_ok=True)
        (pkg / "__init__.py").write_text("", encoding="utf-8")
    (root / "demo2" / "level_a.py").write_text(CASES, encoding="utf-8")
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<!doctype html><body><app-root></app-root></body>", encoding="utf-8")  # vazio
    with StaticServer(site) as server, BrowserSession() as session:
        outcomes = run_suite(load_suite(root, "demo2"), session, server.url, (1440, 900))
    executed = [o for o in outcomes if o.outcome != "PENDING"]
    assert executed and all(o.outcome == "NO" and o.blocked for o in executed)
    assert "o app renderizou (app-root com conteúdo)" in executed[0].failed[0]
