"""Mutação em tempo de execução: o oráculo precisa perceber o app quebrado (navegador real; pytest -m slow)."""

import pytest

from specui.harness import BrowserSession
from specui.oracle import load_suite
from specui.oracle.mutations import (
    Mutation,
    block_events,
    change_text,
    freeze_timers,
    make_readonly,
    remove_all,
    run_mutations,
    summarize,
    text_replace,
    unclamp_overflow,
    verdict_for,
    write_sensitivity,
)

PAGE = """<!doctype html><meta charset="utf-8"><body><app-root><h1>Olá</h1><input id="i" value="x">
<button onclick="document.getElementById('out').textContent='clicado'; start();">Clique</button><p id="out"></p>
<div style="height:100px;overflow:auto"><div style="height:400px">longo</div></div></app-root>
<script>let n = 0; function start() { setInterval(() => { n++; document.getElementById('out2').textContent = String(n); }, 1000); }</script><p id="out2"></p></body>"""

CASES = '''
from playwright.sync_api import expect
from specui.oracle import case

@case("D-A-01", requirements=["D-01"], level="A", task="clicar", expected="texto muda")
def clicks(page, t):
    t.act("clicar", lambda: page.get_by_role("button", name="Clique").click())
    t.eventually("texto mudou", lambda: expect(page.get_by_text("clicado")).to_be_visible())

@case("D-A-02", requirements=["D-01"], level="A", task="texto", expected="Olá")
def hello(page, t):
    t.ok("há Olá", page.get_by_text("Olá").count() == 1)

@case("D-A-03", requirements=["D-01"], level="A", task="digitar", expected="aceita texto")
def typing(page, t):
    t.act("digitar", lambda: page.get_by_role("textbox").fill("novo"))
    t.ok("valor mudou", page.get_by_role("textbox").input_value() == "novo")

@case("D-A-04", requirements=["D-01"], level="A", task="relógio", expected="o contador anda")
def ticking(page, t):
    t.act("iniciar", lambda: page.get_by_role("button", name="Clique").click())
    t.advance(3000)
    t.ok("o contador chegou a 3", page.locator("p").nth(1).inner_text() == "3")

@case("D-A-05", requirements=["D-01"], level="A", task="sempre passa", expected="mutante imortal")
def weak_test(page, t):
    t.ok("a página existe", page.locator("body").count() == 1)

@case("D-A-06", requirements=["D-01"], level="A", task="rolagem", expected="só o bloco rola")
def scrolls(page, t):
    t.ok("há um contêiner rolável", page.evaluate("() => Array.from(document.querySelectorAll('div')).some((d) => d.scrollHeight > d.clientHeight + 2 && getComputedStyle(d).overflowY === 'auto')"))
'''

REQUIREMENTS = "requirements:\n  - {id: D-01, text: x, category: a, info_source: behavior}\n"


@pytest.fixture
def served(tmp_path):
    root = tmp_path / "oracles"
    (root / "demo3").mkdir(parents=True)
    for pkg in (root, root / "demo3"):
        (pkg / "__init__.py").write_text("", encoding="utf-8")
    (root / "demo3" / "level_a.py").write_text(CASES, encoding="utf-8")
    (root / "demo3" / "requirements.yaml").write_text(REQUIREMENTS, encoding="utf-8")
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text(PAGE, encoding="utf-8")
    return load_suite(root, "demo3"), dist


def test_verdict_rules():
    assert verdict_for("YES", "NO", True) == "KILLED"
    assert verdict_for("YES", "PARTIAL", True) == "WEAK"
    assert verdict_for("YES", "YES", True) == "SURVIVED"
    assert verdict_for("YES", "NO", False) == "NOT_APPLIED"  # a mutação não alterou nada
    assert verdict_for("PARTIAL", "NO", True) == "NOT_APPLIED"  # só YES é testável


def test_catalog_targets_exist_in_the_real_suites(repo_root):
    from specui.oracle.mutations import CATALOG

    for task_id, mutations in CATALOG.items():
        suite = load_suite(repo_root / "oracles", task_id)
        ids = {c.id for c in suite.cases}
        assert all(t in ids for m in mutations for t in m.targets), task_id
        assert len({m.id for m in mutations}) == len(mutations)


@pytest.mark.slow
def test_mutations_are_killed_or_survive_as_expected(served, tmp_path):
    suite, dist = served
    catalog = [
        block_events("X1", "block_click", ["click"], ["D-A-01"]),
        remove_all("X2", "button", ["D-A-01"]),
        change_text("X3", "Olá", "Hi", ["D-A-02"]),
        make_readonly("X4", ["D-A-03"]),
        block_events("X5", "block_input_events", ["input"], ["D-A-03"]),
        freeze_timers("X6", ["D-A-04"]),
        unclamp_overflow("X7", ["D-A-06"]),
        text_replace("X8", "Olá", "Oi", ["D-A-02"]),
        remove_all("X9", ".nao-existe", ["D-A-05"]),
        make_readonly("X10", ["D-A-05"]),  # o teste fraco sobrevive: é exatamente o que a mutação quer revelar
    ]
    with BrowserSession() as session:
        rows = run_mutations(suite, session, dist, (1440, 900), "run-x", catalog)
    by = {(r.mutation_id, r.case_id): r for r in rows}
    assert by[("X1", "D-A-01")].verdict == "KILLED"  # o clique é só um passo: sem o efeito não sobra nenhum ponto
    assert by[("X2", "D-A-01")].verdict == "KILLED"
    assert by[("X3", "D-A-02")].verdict == "KILLED"
    assert by[("X4", "D-A-03")].verdict == "KILLED"
    assert by[("X5", "D-A-03")].verdict == "SURVIVED"  # a página demo não depende do evento input: o teste não deve cair
    assert by[("X6", "D-A-04")].verdict == "KILLED"  # iniciar é passo; a contagem era a única asserção
    assert by[("X7", "D-A-06")].verdict == "KILLED"
    assert by[("X8", "D-A-02")].verdict == "KILLED"
    assert by[("X9", "D-A-05")].verdict == "NOT_APPLIED"  # nada para remover
    assert by[("X10", "D-A-05")].verdict == "SURVIVED"
    csv_path = write_sensitivity(rows, tmp_path / "sensitivity.csv")
    assert csv_path.read_text(encoding="utf-8").startswith("run_id,task_id,mutation_id")
    assert summarize(rows)["D-A-05"]["SURVIVED"] == 1


def test_mutation_dataclass_is_frozen():
    m = Mutation("m", "op", "d", ("c",))
    with pytest.raises(AttributeError):
        m.id = "x"  # type: ignore[misc]
