"""Embeddings reais (DINOv2 e CLIP): baixam os modelos na primeira vez. pytest -m slow"""

import shutil

import pytest

from specui.config import load_config
from specui.harness import RenderArtifacts
from specui.metrics import embeddings as emb
from specui.metrics.design2code import blocks_from_ref
from specui.metrics.reference import RefBlock
from specui.models import RunRecord
from specui.stages import StageContext, stage_design2code, stage_embeddings, stage_pixel

pytestmark = pytest.mark.slow

available, why = emb.embeddings_available()
if not available:  # pragma: no cover
    pytest.skip(f"embeddings indisponíveis: {why}", allow_module_level=True)

CACHE = "~/.cache/specui-models"


def test_ves_is_one_for_the_same_image_and_lower_for_a_different_one(tasks):
    easy, hard = tasks[0].image_path, tasks[2].image_path
    same = emb.ves_dinov2(easy, easy, CACHE)
    other = emb.ves_dinov2(easy, hard, CACHE)
    assert same == pytest.approx(1.0, abs=1e-4)
    assert 0.0 < other < same - 0.01


def test_clip_cosine(tasks):
    easy, hard = tasks[0].image_path, tasks[2].image_path
    assert emb.clip_cosine(easy, easy, CACHE) == pytest.approx(1.0, abs=1e-4)
    assert emb.clip_cosine(easy, hard, CACHE) < 0.999


def test_embeddings_are_deterministic(tasks):
    a, b = emb.dinov2_embedding(tasks[1].image_path, CACHE), emb.dinov2_embedding(tasks[1].image_path, CACHE)
    assert (a == b).all() and abs((a @ a) - 1.0) < 1e-9  # L2-normalizado


def test_full_visual_stage_chain_on_a_perfect_copy(repo_root, tasks, tmp_path):
    """Render idêntico ao design e blocos idênticos aos de referência: tudo vale ~1."""
    task = tasks[0]
    figma = tmp_path / "figma"
    figma.mkdir()
    ref = [RefBlock(text="Pomodoro", x0=80, y0=20, x1=220, y1=50, color_rgb=(255, 255, 255)),
           RefBlock(text="25:00", x0=560, y0=300, x1=880, y1=450, color_rgb=(215, 71, 71))]
    import json
    (figma / "blocks.json").write_text(json.dumps({task.id: {"blocks": [b.model_dump(mode="json") for b in ref]}}),
                                       encoding="utf-8")
    cfg = load_config(repo_root / "configs" / "default.yaml",
                      overrides={"references_dir": str(figma), "results_dir": str(tmp_path / "r")})
    out = tmp_path / "out"
    out.mkdir()
    shutil.copyfile(task.image_path, out / "screenshot.png")
    dom = [{"text": b.text, "x": b.x0, "y": b.y0, "w": b.x1 - b.x0, "h": b.y1 - b.y0, "color": list(b.color_rgb)}
           for b in ref]
    rec = RunRecord(run_id="r", run_kind="pilot", cell_key="k", task_id=task.id, difficulty="easy",
                    prompt_kind="no_spec", prompt_id="p", modality="text", rep=0, created_at="t", provider="mock",
                    model_id_requested="m", prompt_sha256="p", envelope_sha256="e", envelope_version="2")
    ctx = StageContext(cfg=cfg, task=task, out_dir=out, record=rec,
                       render=RenderArtifacts(render_ok=True, viewport=(1440, 900), dom_blocks=dom))
    for stage in (stage_design2code, stage_pixel, stage_embeddings):
        stage(ctx)
    assert rec.design2code.block_match == pytest.approx(1.0)
    assert rec.embeddings.ves_dinov2 == pytest.approx(1.0, abs=1e-4)
    assert rec.embeddings.mae == 0.0
    assert rec.design2code.clip_inpainted == pytest.approx(1.0, abs=1e-3)
    assert len(blocks_from_ref(ref)) == 2
