import json
import shutil
from pathlib import Path

import pytest
from PIL import Image

from specui.config import load_config
from specui.harness import RenderArtifacts
from specui.metrics import embeddings as emb
from specui.metrics.pixel import load_rgb, mae, ssim
from specui.models import RunRecord, TechnicalMetrics
from specui.stages import (
    STAGE_GROUPS,
    StageContext,
    default_stages,
    reevaluate_record,
    render_from_disk,
    run_stages,
    stage_design2code,
    stage_embeddings,
    stage_pixel,
    stage_technical,
)

# ----------------------------------------------------------------------------- pixel


def _png(path: Path, color, size=(20, 20)) -> Path:
    Image.new("RGB", size, color).save(path)
    return path


def test_mae_extremes_and_identity(tmp_path):
    black, white = _png(tmp_path / "b.png", (0, 0, 0)), _png(tmp_path / "w.png", (255, 255, 255))
    assert mae(black, black) == 0.0
    assert mae(black, white) == pytest.approx(1.0)
    gray = _png(tmp_path / "g.png", (128, 128, 128))
    assert mae(black, gray) == pytest.approx(128 / 255, abs=1e-6)


def test_mae_resizes_the_render_to_the_design(tmp_path):
    design = _png(tmp_path / "d.png", (100, 100, 100), (40, 40))
    render = _png(tmp_path / "r.png", (100, 100, 100), (20, 20))
    assert mae(render, design) == pytest.approx(0.0, abs=1e-3)


def test_ssim_identity_and_difference(tmp_path):
    a = tmp_path / "a.png"
    Image.effect_noise((64, 64), 40).convert("RGB").save(a)
    b = _png(tmp_path / "b.png", (0, 0, 0), (64, 64))
    assert ssim(a, a) == pytest.approx(1.0)
    assert ssim(a, b) < 0.5


def test_transparency_is_composited_on_white(tmp_path):
    path = tmp_path / "t.png"
    Image.new("RGBA", (4, 4), (0, 0, 0, 0)).save(path)
    assert load_rgb(path).min() == 1.0


def test_real_design_against_itself(tasks):
    design = tasks[0].image_path
    assert mae(design, design) == 0.0
    assert ssim(design, design) == pytest.approx(1.0)


# ----------------------------------------------------------------------------- estágios


@pytest.fixture
def cfg(repo_root, tmp_path):
    figma = tmp_path / "figma"
    figma.mkdir()
    shutil.copyfile(repo_root / "tests" / "fixtures" / "figma_nodes_sample.json", figma / "nodes.raw.json")
    config = load_config(repo_root / "configs" / "default.yaml",
                         overrides={"references_dir": str(figma), "results_dir": str(tmp_path / "results"),
                                    "enable_embeddings": False})
    return config


@pytest.fixture
def task(tasks):
    return tasks[0].model_copy(update={"figma_node_id": "12:345"})


DOM = [  # os blocos do fixture do Figma, como o DOM os veria
    {"text": "Pomodoro", "x": 80, "y": 20, "w": 140, "h": 30, "color": [255, 255, 255]},
    {"text": "Foco Total", "x": 600, "y": 200, "w": 240, "h": 44, "color": [215, 71, 71]},
    {"text": "25:00", "x": 560, "y": 280, "w": 320, "h": 150, "color": [215, 71, 71]},
]


def _record(run_id="run-1", status="done", **kw) -> RunRecord:
    return RunRecord(
        run_id=run_id, run_kind="main", cell_key="k", task_id="easy_pomodoro", difficulty="easy",
        prompt_kind="no_spec", prompt_id="easy_pomodoro/no_spec", modality="text", rep=0,
        created_at="2026-10-09T00:00:00+00:00", provider="mock", model_id_requested="m",
        prompt_sha256="p", envelope_sha256="e", envelope_version="2", status=status,
        paths={"run_dir": f"runs/{run_id}"}, **kw,
    )


def _ctx(cfg, task, tmp_path, dom=DOM, shot: Path | None = None) -> StageContext:
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    shutil.copyfile(shot or task.image_path, out / "screenshot.png")
    render = RenderArtifacts(render_ok=True, viewport=(1440, 900), dom_blocks=dom, console_errors=["e1"],
                             axe_violations={"critical": 2})
    return StageContext(cfg=cfg, task=task, render=render, out_dir=out, record=_record())


def test_design2code_stage_scores_a_faithful_page(cfg, task, tmp_path):
    ctx = _ctx(cfg, task, tmp_path)
    stage_design2code(ctx)
    m = ctx.record.design2code
    assert m.reference_source == "figma" and m.n_ref_blocks == 6
    assert m.text > 0.9 and m.position > 0.99 and m.color > 0.99
    assert m.block_match < 1  # 3 dos 6 blocos de referência não existem na página
    pairs = json.loads((ctx.out_dir / "pairs.json").read_text(encoding="utf-8"))
    assert len(pairs["pairs"]) == 3 and len(pairs["unmatched_ref"]) == 3


def test_design2code_stage_degrades_without_reference(cfg, task, tmp_path):
    ctx = _ctx(cfg.model_copy(update={"references_dir": str(tmp_path / "vazio")}), task, tmp_path)
    stage_design2code(ctx)  # não levanta
    assert ctx.record.design2code is None
    assert any("referência indisponível" in e for e in ctx.record.errors)
    assert ctx.record.status == "done"  # falta de referência não é falha do modelo


def test_pixel_stage_fills_mae_and_ssim(cfg, task, tmp_path):
    ctx = _ctx(cfg, task, tmp_path)
    stage_pixel(ctx)
    assert ctx.record.embeddings.mae == 0.0 and ctx.record.embeddings.ssim == pytest.approx(1.0)
    assert ctx.record.embeddings.ves_dinov2 is None  # o VES é de outro estágio


def test_technical_stage_counts_console_and_axe(cfg, task, tmp_path):
    ctx = _ctx(cfg, task, tmp_path)
    stage_technical(ctx)
    assert ctx.record.technical.console_error_count == 1 and ctx.record.technical.axe_violations == {"critical": 2}


def test_embeddings_stage_is_a_noop_when_disabled(cfg, task, tmp_path):
    ctx = _ctx(cfg, task, tmp_path)
    stage_embeddings(ctx)
    assert ctx.record.embeddings is None and ctx.record.errors == []


def test_embeddings_stage_reports_missing_dependency(cfg, task, tmp_path, monkeypatch):
    monkeypatch.setattr(emb, "embeddings_available", lambda: (False, "torch não instalado"))
    ctx = _ctx(cfg.model_copy(update={"enable_embeddings": True}), task, tmp_path)
    stage_embeddings(ctx)
    assert ctx.record.embeddings is None
    assert ctx.record.errors == ["embeddings desativados: torch não instalado"]  # None + motivo, sem falha


def test_stage_groups_and_selection():
    assert set(STAGE_GROUPS) == {"technical", "visual", "code", "functional"}
    assert [s.__name__ for s in default_stages()] == [
        "stage_technical", "stage_design2code", "stage_pixel", "stage_embeddings", "stage_code_quality", "stage_functional"]
    assert next(s.__name__ for s in default_stages(groups=["visual"])) == "stage_design2code"
    with pytest.raises(ValueError, match="desconhecidos"):
        default_stages(groups=["nao_existe"])


def test_run_stages_isolates_failures(cfg, task, tmp_path):
    def boom(ctx):
        raise RuntimeError("quebrou")

    ctx = _ctx(cfg, task, tmp_path)
    failed = run_stages(ctx, [boom, stage_technical])
    assert failed == ["boom"] and ctx.record.status == "metric_error"
    assert ctx.record.errors == ["boom: RuntimeError: quebrou"]
    assert ctx.record.technical is not None  # o estágio seguinte rodou


# ----------------------------------------------------------------------------- reavaliação


def _stored_run(tmp_path, task, status="done", errors=None) -> tuple[Path, RunRecord]:
    root = tmp_path / "results"
    out = root / "runs" / "run-1"
    out.mkdir(parents=True)
    shutil.copyfile(task.image_path, out / "screenshot.png")
    (out / "dom_blocks.json").write_text(json.dumps(DOM), encoding="utf-8")
    (out / "css_snapshot.json").write_text(json.dumps({"elements": [], "rules": []}), encoding="utf-8")
    rec = _record(status=status, technical=TechnicalMetrics(console_errors=["e1"], console_error_count=1),
                  errors=errors or [])
    rec.paths.update({"screenshot": "screenshot.png", "dom_blocks": "dom_blocks.json", "css_snapshot": "css_snapshot.json"})
    rec.exec.render_ok = True
    return root, rec


def test_render_from_disk_rebuilds_the_artifacts(cfg, task, tmp_path):
    root, rec = _stored_run(tmp_path, task)
    render = render_from_disk(rec, root / "runs" / "run-1", (1440, 900))
    assert render.render_ok and render.dom_blocks == DOM and render.css_snapshot["rules"] == []
    assert render.console_errors == ["e1"] and render.screenshot_path.endswith("screenshot.png")


def test_reevaluate_visual_group_from_stored_artifacts(cfg, task, tmp_path):
    root, rec = _stored_run(tmp_path, task, status="metric_error",
                            errors=["stage_design2code: RuntimeError: antigo", "outra coisa"])
    out = reevaluate_record(cfg, root, rec, task, groups=["visual"])
    assert out.design2code is not None and out.design2code.n_matched == 3
    assert out.embeddings.mae == 0.0
    assert out.status == "done"  # o único erro era do estágio refeito
    assert out.errors == ["outra coisa"]
    assert out.paths["run_dir"] == "runs/run-1" and out.design2code.pairs_path == "pairs.json"
    assert (root / "runs" / "run-1" / "pairs.json").is_file()
    assert out.technical.console_errors == ["e1"]  # outros grupos intactos


def test_reevaluate_keeps_metric_error_if_another_stage_is_still_broken(cfg, task, tmp_path):
    root, rec = _stored_run(tmp_path, task, status="metric_error", errors=["stage_functional: X: y"])
    assert reevaluate_record(cfg, root, rec, task, groups=["visual"]).status == "metric_error"


def test_reevaluate_rejects_runs_without_render(cfg, task, tmp_path):
    root, rec = _stored_run(tmp_path, task, status="format_failure")
    with pytest.raises(ValueError, match="não tem render"):
        reevaluate_record(cfg, root, rec, task)
