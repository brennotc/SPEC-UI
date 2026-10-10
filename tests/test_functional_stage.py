"""`stage_functional` e a reavaliação do grupo `functional` (navegador real; pytest -m slow)."""

import pytest

from specui.config import load_config
from specui.harness import BrowserSession
from specui.models import RunRecord
from specui.stages import reevaluate_record

pytestmark = pytest.mark.slow

PAGE = """<!doctype html><meta charset="utf-8"><body><app-root><h1>Olá</h1>
<button id="b" onclick="document.getElementById('out').textContent='clicado'">Clique</button><p id="out"></p></app-root></body>"""

CASES = '''
from playwright.sync_api import expect
from specui.oracle import case

@case("D-A-01", requirements=["D-01"], level="A", task="clicar", expected="texto muda")
def clicks(page, t):
    t.act("clicar", lambda: page.get_by_role("button", name="Clique").click())
    t.eventually("texto mudou", lambda: expect(page.get_by_text("clicado")).to_be_visible())

@case("D-A-02", requirements=["D-02"], level="A", task="x", expected="y")
def half(page, t):
    t.ok("existe", page.get_by_text("Olá").count() == 1)
    t.ok("falta", page.get_by_text("Tchau").count() == 1, "faltou o Tchau")

@case("D-B-01", requirements=["D-S01"], level="B", task="x", expected="y")
def spec_only(page, t):
    t.ok("sempre falha", False)
'''

REQUIREMENTS = """requirements:
  - {id: D-01, text: clicar, category: a, info_source: behavior}
  - {id: D-02, text: existir, category: a, info_source: image}
  - {id: D-S01, text: da spec, category: s, info_source: spec_only}
"""


@pytest.fixture
def stored(repo_root, tasks, tmp_path):
    task = tasks[0]
    oracles = tmp_path / "oracles"
    (oracles / task.id).mkdir(parents=True)
    for pkg in (oracles, oracles / task.id):
        (pkg / "__init__.py").write_text("", encoding="utf-8")
    (oracles / task.id / "level_a.py").write_text(CASES.replace('"D-B-01"', '"D-B-01"'), encoding="utf-8")
    (oracles / task.id / "requirements.yaml").write_text(REQUIREMENTS, encoding="utf-8")
    root = tmp_path / "results"
    run_dir = root / "runs" / "run-1"
    (run_dir / "dist").mkdir(parents=True)
    (run_dir / "dist" / "index.html").write_text(PAGE, encoding="utf-8")
    cfg = load_config(repo_root / "configs" / "default.yaml",
                      overrides={"oracles_dir": str(oracles), "results_dir": str(root), "enable_embeddings": False})
    rec = RunRecord(
        run_id="run-1", run_kind="main", cell_key="k", task_id=task.id, difficulty=task.difficulty,
        prompt_kind="no_spec", prompt_id=f"{task.id}/no_spec", modality="text", rep=0,
        created_at="2026-10-09T00:00:00+00:00", provider="mock", model_id_requested="m", prompt_sha256="p",
        envelope_sha256="e", envelope_version="2", paths={"run_dir": "runs/run-1", "dist_dir": "dist"},
    )
    rec.exec.render_ok = True
    return cfg, root, rec, task


def test_functional_group_runs_the_suite_against_the_stored_dist(stored):
    cfg, root, rec, task = stored
    with BrowserSession() as session:
        out = reevaluate_record(cfg, root, rec, task, groups=["functional"], session=session)
    assert out.status == "done" and out.errors == []
    f = out.functional
    assert [c.outcome for c in f.cases] == ["YES", "PARTIAL", "NO"]
    assert f.accuracy_a == pytest.approx(0.75)  # (1 + 0,5) / 2: só o nível A
    assert f.accuracy_b == 0.0
    assert f.accuracy_a_restricted == pytest.approx(0.75)  # sem material_shown = accuracy_a
    assert f.suite_sha256 and len(f.suite_sha256) == 64


def test_functional_group_without_a_browser_session_is_noted_not_fatal(stored):
    cfg, root, rec, task = stored
    out = reevaluate_record(cfg, root, rec, task, groups=["functional"])
    assert out.functional is None
    assert any("sem servidor/navegador" in e for e in out.errors)
    assert out.status == "done"


def test_reevaluation_restamps_the_oracle_that_actually_ran(stored):
    """Se o oráculo mudou desde a geração, o record não pode ficar com o hash antigo ao lado da nota nova."""
    cfg, root, rec, task = stored
    rec.oracle_content_sha256, rec.oracle_suite_tag, rec.oracle_dirty = "0" * 64, "oracle-v0", False
    rec.pending_sha256, rec.mention_patterns_sha256, rec.oracle_tree_hash = "old", "old", "oldtree"
    rec.playwright_version, rec.browser_version = "0.0", "old-chromium"
    with BrowserSession() as session:
        out = reevaluate_record(cfg, root, rec, task, groups=["functional"], session=session)
        browser = session.versions()
    assert out.oracle_content_sha256 != "0" * 64 and len(out.oracle_content_sha256) == 64
    assert out.oracle_suite_tag is None and out.oracle_tree_hash is None  # oracles_dir de teste fica fora do git
    assert out.pending_sha256 != "old" and out.mention_patterns_sha256 != "old"
    assert (out.playwright_version, out.browser_version) == browser and out.browser_version != "old-chromium"
    assert out.functional.suite_sha256 == out.oracle_content_sha256 and out.functional.suite_git_tag is None
