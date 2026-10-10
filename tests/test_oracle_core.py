"""Núcleo dos oráculos: regra de resultado, métrica funcional, lint, rastreabilidade e proveniência."""

import subprocess
import textwrap
from pathlib import Path

import pytest
from playwright.sync_api import Error as PlaywrightError

from specui.metrics.functional import (
    accuracy,
    accuracy_restricted,
    compatible,
    compute_functional,
)
from specui.models import CaseOutcome
from specui.oracle import Checks, build_traceability, classify, lint_suite, load_suite
from specui.oracle.protocol import AssertionRecord
from specui.oracle.provenance import (
    content_sha256,
    freeze_problems,
    mention_patterns_sha256,
    pending_sha256,
    read_provenance,
)
from specui.oracle.requirements import Requirement, load_pending, load_requirements


def rec(*statuses: str) -> list[AssertionRecord]:
    return [AssertionRecord(f"a{i}", s) for i, s in enumerate(statuses)]  # type: ignore[arg-type]


# ---------------------------------------------------------------- regra de resultado


@pytest.mark.parametrize(
    "statuses, crashed, blocked, expected",
    [
        (("pass", "pass"), False, False, "YES"),
        (("pass",), False, False, "YES"),
        (("pass", "fail"), False, False, "PARTIAL"),
        (("fail", "pass", "fail"), False, False, "PARTIAL"),
        (("fail", "fail"), False, False, "NO"),
        ((), False, False, "NO"),  # sem asserção nenhuma: NO (o lint pega o caso mal escrito)
        (("step", "step", "pass"), False, False, "YES"),  # passos (ações/pré-condições que deram certo) não pontuam
        (("step", "step", "fail"), False, False, "NO"),  # o app fez a ação e o resultado não veio: antes valia PARTIAL
        (("step", "step"), False, False, "NO"),  # só passos: nenhuma asserção pontuada
        (("step", "pass", "fail"), False, False, "PARTIAL"),
        (("pass", "pass"), True, False, "NO"),  # exceção inesperada escapou
        (("pass", "pass"), False, True, "NO"),  # pré-condição falhou
        (("pass", "pending", "pending"), False, False, "YES"),  # PENDING não pontua
        (("fail", "pending"), False, False, "NO"),
        (("pending", "pending"), False, False, "NO"),
    ],
)
def test_classify(statuses, crashed, blocked, expected):
    assert classify(rec(*statuses), crashed=crashed, blocked=blocked) == expected


def test_checks_never_raise_on_failed_assertions():
    t = Checks(None)  # type: ignore[arg-type]
    assert t.ok("verdadeira", True) and not t.ok("falsa", False, "motivo")
    assert t.eventually("expect que passa", lambda: None)
    assert not t.eventually("expect que falha", lambda: (_ for _ in ()).throw(AssertionError("x != y")))
    assert not t.act("ação que quebra", lambda: (_ for _ in ()).throw(PlaywrightError("elemento sumiu")))
    t.pending("depende de decisão", "PD-E1")
    assert (t.n_pass, t.n_fail) == (2, 3) and len(t.scored) == 5 and len(t.records) == 6
    assert t.act("ação que funciona", lambda: None) is True
    assert (t.n_pass, t.n_steps, len(t.scored)) == (2, 1, 5)  # o passo bem-sucedido não pontua
    assert t.failed()[0] == "falsa :: motivo" and "AssertionError: x != y" in t.failed()[1]


def test_require_blocks_the_case():
    from specui.oracle.protocol import BlockedError

    t = Checks(None)  # type: ignore[arg-type]
    t.require("pré-condição boa", True)
    with pytest.raises(BlockedError):
        t.require("pré-condição ruim", False, "faltou o botão")
    assert (t.n_pass, t.n_steps, t.n_fail) == (0, 1, 1)  # a que passou é passo; a que falhou pontua como falha
    assert t.failed() == ["pré-condição ruim :: faltou o botão"]


def test_advance_swallows_errors_thrown_by_app_timers():
    from types import SimpleNamespace

    calls = []

    def run_for(ms):
        calls.append(ms)
        if ms == 3000:
            raise PlaywrightError("Clock.run_for: TypeError: tick quebrou")

    t = Checks(SimpleNamespace(clock=SimpleNamespace(run_for=run_for)))  # type: ignore[arg-type]
    assert t.advance(1000) is True and t.advance(3000) is False
    assert calls == [1000, 3000] and t.js_errors() == ["TypeError: tick quebrou"]


def test_js_errors_filter_audio_autoplay_noise():
    t = Checks(None, ["Uncaught (in promise) NotAllowedError: play() failed", "TypeError: x is undefined"])  # type: ignore[arg-type]
    assert t.js_errors() == ["TypeError: x is undefined"]


# ---------------------------------------------------------------- métrica funcional


def out(case_id, outcome, level="A", requirements=()):
    return CaseOutcome(case_id=case_id, level=level, outcome=outcome, requirements=list(requirements))


def test_accuracy_is_webgen_formula_and_pending_is_excluded():
    outcomes = [out("1", "YES"), out("2", "PARTIAL"), out("3", "NO"), out("4", "YES"), out("5", "PENDING")]
    assert accuracy(outcomes) == pytest.approx((1 + 0.5 + 0 + 1) / 4)
    assert accuracy([out("p", "PENDING")]) is None and accuracy([]) is None


def test_blocked_no_counts_zero_and_stays_in_the_denominator():
    blocked = CaseOutcome(case_id="b", level="A", outcome="NO", blocked=True)
    assert accuracy([out("1", "YES"), blocked]) == 0.5


def test_accuracy_by_level():
    outcomes = [out("A1", "YES"), out("A2", "NO"), out("B1", "YES", "B")]
    assert accuracy(outcomes, "A") == 0.5 and accuracy(outcomes, "B") == 1.0
    m = compute_functional(outcomes, suite_sha256="x", suite_git_tag="oracle-v1")
    assert (m.accuracy_a, m.accuracy_b, m.accuracy_a_restricted) == (0.5, 1.0, 0.5)
    assert m.suite_git_tag == "oracle-v1" and len(m.cases) == 3


REQS = {
    "R-img": Requirement(id="R-img", text="t", category="a", info_source="image"),
    "R-beh": Requirement(id="R-beh", text="t", category="a", info_source="behavior"),
    "R-spec": Requirement(id="R-spec", text="t", category="s", info_source="spec_only"),
}


def test_restricted_accuracy_follows_the_material_shown():
    outcomes = [out("c1", "YES", requirements=["R-img"]), out("c2", "NO", requirements=["R-beh"]),
                out("c3", "NO", requirements=["R-img", "R-beh"])]
    assert accuracy_restricted(outcomes, REQS, None) == pytest.approx(1 / 3)  # sem material: todos os casos
    assert accuracy_restricted(outcomes, REQS, "image") == 1.0  # só o que dá para ver na imagem
    assert accuracy_restricted(outcomes, REQS, "image+brief") == pytest.approx(1 / 3)  # imagem + comportamento
    assert accuracy_restricted(outcomes, REQS, "image+prototype") == pytest.approx(1 / 3)
    assert accuracy_restricted([out("c4", "NO", requirements=["R-spec"])], REQS, "image+brief") is None
    assert not compatible(["R-spec"], REQS, "image+prototype") and compatible(["R-beh"], REQS, "image+brief")
    assert compatible(["desconhecido"], REQS, "image")  # requisito desconhecido: não elimina o caso


# ---------------------------------------------------------------- suíte sintética: carga, lint, rastreabilidade

DEMO_LEVEL_A = '''
from specui.oracle import case

@case("D-A-01", requirements=["D-01"], level="A", task="abrir", expected="título visível")
def title_visible(page, t):
    t.ok("título", page.get_by_text("Olá").count() > 0)

@case("D-A-02", requirements=["D-02", "D-02"], level="A", task="x", expected="y")
def second(page, t):
    t.ok("algo", True)

@case("D-A-10", requirements=["D-03"], level="A", task="x", expected="y", pending="PD-D1")
def pending_case(page, t):
    pass

@case("D-A-03", requirements=["D-99"], level="A", task="x", expected="y")
def unknown_requirement(page, t):
    t.ok("algo", True)

@case("D-A-04", requirements=["D-01"], level="A", task="x", expected="y")
def no_assertions(page, t):
    page.title()

@case("D-A-05", requirements=["D-01"], level="A", task="x", expected="y")
def only_steps(page, t):
    t.require("a página existe", page.title() is not None)
    t.act("clicar", lambda: page.locator("body").click())
'''

DEMO_REQS = """
task_id: demo
requirements:
  - {id: D-01, text: "título", category: a, info_source: image, mention_patterns: ["t[ií]tulo"]}
  - {id: D-02, text: "botão", category: a, info_source: behavior}
  - {id: D-03, text: "ambíguo", category: c, info_source: behavior, pending: [PD-D1]}
  - {id: D-04, text: "só visual", category: b, info_source: image}
  - {id: D-05, text: "sem caso", category: a, info_source: image}
  - {id: D-06, text: "ambíguo sem pendência", category: c, info_source: behavior}
  - {id: D-S1, text: "da spec", category: s, info_source: spec_only}
"""

DEMO_PENDING = """
pending:
  - {id: PD-D1, question: "como?", rule: 2, options: ["a", "b"]}
"""


@pytest.fixture
def demo_oracles(tmp_path) -> Path:
    root = tmp_path / "oracles"
    (root / "demo").mkdir(parents=True)
    (root / "__init__.py").write_text("", encoding="utf-8")
    (root / "common").mkdir()
    (root / "common" / "__init__.py").write_text("", encoding="utf-8")
    (root / "demo" / "__init__.py").write_text("", encoding="utf-8")
    (root / "demo" / "level_a.py").write_text(DEMO_LEVEL_A, encoding="utf-8")
    (root / "demo" / "requirements.yaml").write_text(DEMO_REQS, encoding="utf-8")
    (root / "demo" / "pending.yaml").write_text(DEMO_PENDING, encoding="utf-8")
    return root


def test_requirements_and_pending_load(demo_oracles):
    reqs = load_requirements(demo_oracles, "demo")
    assert [r.id for r in reqs][:3] == ["D-01", "D-02", "D-03"] and reqs[0].mention_patterns == ["t[ií]tulo"]
    assert load_pending(demo_oracles, "demo")[0].rule == 2
    assert load_pending(demo_oracles, "nao_existe") == []


def test_invalid_requirement_data_fails_on_load(tmp_path):
    (tmp_path / "t").mkdir()
    (tmp_path / "t" / "requirements.yaml").write_text(
        "requirements:\n  - {id: X, text: t, category: a, info_source: image, mention_patterns: ['(']}\n", encoding="utf-8")
    with pytest.raises(ValueError):  # regex inválida
        load_requirements(tmp_path, "t")
    (tmp_path / "t" / "requirements.yaml").write_text(
        "requirements:\n  - {id: X, text: t, category: a, info_source: image}\n  - {id: X, text: u, category: a, info_source: image}\n",
        encoding="utf-8")
    with pytest.raises(ValueError, match="repetidos"):
        load_requirements(tmp_path, "t")


def test_load_suite_orders_cases_and_marks_pending(demo_oracles):
    suite = load_suite(demo_oracles, "demo")
    assert [c.id for c in suite.cases] == ["D-A-01", "D-A-02", "D-A-03", "D-A-04", "D-A-05", "D-A-10"]  # ordem natural
    assert suite.cases[-1].pending == "PD-D1" and suite.cases[0].task_id == "demo"
    assert load_suite(demo_oracles, "demo").cases == suite.cases  # recarregar não duplica o registro


def test_lint_finds_authoring_problems(demo_oracles):
    suite = load_suite(demo_oracles, "demo")
    problems = "\n".join(lint_suite(suite, demo_oracles))
    assert "D-A-03: requisitos inexistentes ['D-99']" in problems
    assert "D-A-04: o caso não tem nenhuma asserção pontuada" in problems
    assert "D-A-05: o caso não tem nenhuma asserção pontuada" in problems  # só require/act: daria NO por "sem asserção pontuada"
    assert "D-A-01:" not in problems and "D-A-02:" not in problems  # os casos corretos passam no lint
    assert "D-A-10" not in problems  # caso pendente válido


def test_lint_rejects_non_semantic_selectors_and_missing_pending(demo_oracles):
    (demo_oracles / "demo" / "level_b.py").write_text(textwrap.dedent('''
        from specui.oracle import case

        @case("D-B-01", requirements=["D-S1"], level="B", task="x", expected="y", pending="PD-NAO-EXISTE")
        def a(page, t):
            t.ok("x", page.locator("#timer").count() == 1)

        @case("D-B-02", requirements=["D-S1"], level="B", task="x", expected="y")
        def b(page, t):
            t.ok("x", page.locator(".botao").count() + page.locator('[data-testid="x"]').count() + page.get_by_test_id("y").count())
            t.ok("y", page.locator("input[type=date]").count() == 0)  # permitido: tag + atributo de tipo
    '''), encoding="utf-8")
    problems = "\n".join(lint_suite(load_suite(demo_oracles, "demo"), demo_oracles))
    assert "pendência PD-NAO-EXISTE não existe" in problems
    assert problems.count("seletor CSS por id/classe") == 2 and "data-testid" in problems
    assert "input[type=date]" not in problems


def test_lint_catches_duplicate_ids(demo_oracles):
    (demo_oracles / "demo" / "level_b.py").write_text(
        'from specui.oracle import case\n\n@case("D-A-01", requirements=["D-S1"], level="B", task="x", expected="y")\n'
        "def dup(page, t):\n    t.ok('x', True)\n", encoding="utf-8")
    assert any("id de caso repetido: D-A-01" in p for p in lint_suite(load_suite(demo_oracles, "demo"), demo_oracles))


def test_traceability_matrix_and_coverage_problems(demo_oracles):
    suite = load_suite(demo_oracles, "demo")
    markdown, problems = build_traceability(suite, load_requirements(demo_oracles, "demo"))
    assert "| D-01 |" in markdown and "coberto" in markdown
    assert "| D-03 | ambíguo | c | behavior | D-A-10 (pendente) | pendente (PD-D1) |" in markdown
    assert "visual (Design2Code/VES)" in markdown
    assert "D-05: requisito testável sem caso de nível A executável" in problems
    assert "D-06: categoria c sem pendência declarada" in problems
    assert "D-S1: requisito da spec sem caso de nível B" in problems
    assert not any(p.startswith(("D-01", "D-02", "D-03", "D-04")) for p in problems)


# ---------------------------------------------------------------- proveniência (repositório git temporário)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(demo_oracles) -> Path:
    root = demo_oracles.parent
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "core.autocrlf", "false")
    return root


def test_provenance_before_and_after_freezing(repo):
    oracles = repo / "oracles"
    prov = read_provenance(repo, oracles)
    assert prov.tag is None and prov.tree_hash is None  # nada commitado ainda
    assert any("nenhuma tag" in p for p in freeze_problems(prov))

    (oracles / "VERSION").write_text("oracle-v1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "oraculo")
    _git(repo, "tag", "oracle-v1")
    prov = read_provenance(repo, oracles)
    assert prov.tag == "oracle-v1" and prov.tree_hash and not prov.dirty
    assert prov.version_file == "oracle-v1" and freeze_problems(prov) == []

    # outro arquivo do repositório muda: a tag continua válida (a árvore de oracles/ é a mesma)
    (repo / "outro.txt").write_text("x", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "outro")
    assert read_provenance(repo, oracles).tag == "oracle-v1"

    # mexer no oráculo: sujo e, depois de commitar sem nova tag, sem tag
    (oracles / "demo" / "level_a.py").write_text(DEMO_LEVEL_A + "\n# mudou\n", encoding="utf-8")
    dirty = read_provenance(repo, oracles)
    assert dirty.dirty and any("não commitadas" in p for p in freeze_problems(dirty))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "mexeu")
    moved = read_provenance(repo, oracles)
    assert moved.tag is None and not moved.dirty and moved.content_sha256 != prov.content_sha256


def test_version_file_must_match_the_tag(repo):
    oracles = repo / "oracles"
    (oracles / "VERSION").write_text("oracle-v9\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "x")
    _git(repo, "tag", "oracle-v1")
    assert any("difere da tag" in p for p in freeze_problems(read_provenance(repo, oracles)))


def test_hashes_track_the_right_things(demo_oracles):
    base = (content_sha256(demo_oracles), pending_sha256(demo_oracles), mention_patterns_sha256(demo_oracles))
    (demo_oracles / "demo" / "CHANGELOG.md").write_text("x", encoding="utf-8")
    (demo_oracles / "demo" / "traceability.md").write_text("gerado", encoding="utf-8")
    (demo_oracles / "demo" / "__pycache__").mkdir()
    (demo_oracles / "demo" / "__pycache__" / "a.py").write_text("lixo", encoding="utf-8")
    assert content_sha256(demo_oracles) == base[0]  # docs geradas e caches não mudam o instrumento
    (demo_oracles / "demo" / "pending.yaml").write_text(DEMO_PENDING + "# decidido\n", encoding="utf-8")
    assert pending_sha256(demo_oracles) != base[1] and content_sha256(demo_oracles) != base[0]
    assert mention_patterns_sha256(demo_oracles) == base[2]
    reqs = (demo_oracles / "demo" / "requirements.yaml")
    reqs.write_text(DEMO_REQS.replace('["t[ií]tulo"]', '["t[ií]tulo", "cabe[cç]alho"]'), encoding="utf-8")
    assert mention_patterns_sha256(demo_oracles) != base[2]
    reqs.write_text(DEMO_REQS.replace("category: a, info_source: behavior}", "category: a,   info_source: behavior}"),
                    encoding="utf-8")
    assert mention_patterns_sha256(demo_oracles) == base[2]  # reformatar não muda os padrões
