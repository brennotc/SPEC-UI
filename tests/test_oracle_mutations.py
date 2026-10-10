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
    neutralize_filters,
    remove_all,
    run_mutations,
    run_mutations_with_baseline,
    summarize,
    text_replace,
    unclamp_overflow,
    verdict_for,
    write_baseline,
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


FILTER_PAGE = """<!doctype html><meta charset="utf-8"><body><app-root>
<select aria-label="filtro" style="position:absolute;top:90px;left:20px"><option value="">todos</option><option value="a">só alfa</option></select>
<ul style="position:absolute;top:150px"><li>alfa</li><li>beta</li></ul>
<input aria-label="descrição" style="position:absolute;top:800px;left:20px">
<button style="position:absolute;top:800px;left:300px" onclick="document.getElementById('out').textContent=document.querySelector('input').value">ok</button>
<p id="out" style="position:absolute;top:840px"></p></app-root>
<script>document.querySelector('select').addEventListener('change', (e) => {
  document.querySelectorAll('li').forEach((li) => { li.style.display = e.target.value === 'a' && li.textContent !== 'alfa' ? 'none' : ''; }); });</script></body>"""

FILTER_CASES = '''
from specui.oracle import case

@case("F-A-01", requirements=["F-01"], level="A", task="filtrar", expected="beta some")
def filters(page, t):
    t.act("escolher alfa", lambda: page.get_by_role("combobox").select_option("a"))
    t.require("a beta fica oculta", not page.get_by_text("beta", exact=True).is_visible())
    t.ok("a alfa continua visível", page.get_by_text("alfa", exact=True).is_visible())

@case("F-A-02", requirements=["F-01"], level="A", task="formulário", expected="o texto vai para a saída")
def form(page, t):
    t.act("digitar", lambda: page.get_by_label("descrição").fill("oi"))
    t.act("clicar", lambda: page.get_by_role("button", name="ok").click())
    t.ok("a saída mostra o texto", page.locator("#out").inner_text() == "oi")
'''


@pytest.mark.slow
def test_neutralize_filters_kills_only_the_filter_case(tmp_path):
    root = tmp_path / "oracles"
    (root / "demo4").mkdir(parents=True)
    for pkg in (root, root / "demo4"):
        (pkg / "__init__.py").write_text("", encoding="utf-8")
    (root / "demo4" / "level_a.py").write_text(FILTER_CASES, encoding="utf-8")
    (root / "demo4" / "requirements.yaml").write_text(
        "requirements:\n  - {id: F-01, text: x, category: a, info_source: behavior}\n", encoding="utf-8")
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text(FILTER_PAGE, encoding="utf-8")
    suite = load_suite(root, "demo4")
    with BrowserSession() as session:
        rows = run_mutations(suite, session, dist, (1440, 900), "run-f", [neutralize_filters("X-F", ["F-A-01", "F-A-02"])])
        none_found = run_mutations(suite, session, dist, (1440, 900), "run-f", [neutralize_filters("X-N", ["F-A-01"])])
    by = {r.case_id: r for r in rows}
    assert by["F-A-01"].verdict == "KILLED"  # a filtragem ficou inerte
    assert by["F-A-02"].verdict == "SURVIVED"  # o formulário do rodapé segue funcionando: a mutação é específica do filtro
    assert none_found[0].verdict == "KILLED"
    blank = tmp_path / "blank"
    blank.mkdir()
    (blank / "index.html").write_text("<!doctype html><body><app-root><p>sem filtro</p></app-root></body>", encoding="utf-8")
    with BrowserSession() as session:
        rows, baseline = run_mutations_with_baseline(
            load_suite(root, "demo4"), session, blank, (1440, 900), "run-b", [neutralize_filters("X-B", ["F-A-02"])])
    assert rows[0].verdict == "NOT_APPLIED"  # baseline não era YES (a página não tem o formulário)
    # ... e o NOT_APPLIED vem com o diagnóstico do baseline (o mesmo que o failure_report grava)
    assert "outcome=NO" in rows[0].detail and "blocked=" in rows[0].detail and "failed=" in rows[0].detail
    assert [(b.case_id, b.outcome, b.blocked) for b in baseline] == [("F-A-02", "NO", False)]  # act falhando e ok falhando: NO sem bloqueio
    assert baseline[0].failed_assertions and baseline[0].run_id == "run-b" and baseline[0].duration_ms >= 0
    out = write_baseline(baseline, tmp_path / "sensitivity_baseline.csv")
    header, line = out.read_text(encoding="utf-8-sig").splitlines()[:2]
    assert header.split(";")[:4] == ["run_id", "task_id", "case_id", "outcome"] and line.split(";")[3] == "NO"
