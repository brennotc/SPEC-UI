"""Ponta a ponta com o gerador simulado, Angular e Chromium reais (lento): pytest -m slow"""

import json
import os
import shutil

import pytest

from specui.config import load_config
from specui.models import Generator, default_workspace_dir
from specui.pipeline import run_experiment
from specui.storage import RunStore
from specui.tasks import png_size

pytestmark = pytest.mark.slow

if not shutil.which("node"):  # pragma: no cover
    pytest.skip("Node não encontrado", allow_module_level=True)


def _cfg(repo_root, tmp_path, variant: str):
    ws = os.environ.get("SPECUI_TEST_WORKSPACE", default_workspace_dir() + "-test")
    cfg = load_config(
        repo_root / "configs" / "default.yaml",
        overrides={"results_dir": str(tmp_path / "results"), "workspace_dir": ws, "repetitions": 1,
                   "tasks": ["easy"], "modalities": ["text"], "prompt_sources": ["no_spec"]},
    )
    gen = Generator(provider="mock", model_id="mock-1", mock_variant=variant, request_delay_s=0)
    return cfg.model_copy(update={"generators": [gen]})


def test_mock_run_end_to_end(repo_root, tmp_path):
    cfg = _cfg(repo_root, tmp_path, "ok")
    summary = run_experiment(cfg)
    assert summary.by_status == {"done": 1}

    store = RunStore(cfg.path("results_dir"), "main")
    (rec,) = store.load_records()
    assert rec.exec.executable is True and rec.exec.build_time_s and rec.exec.build_time_s < 120
    shot = store.artifact(rec, "screenshot")
    assert png_size(shot) == (1440, 900)  # viewport = frame do Figma, escala 1x
    blocks = json.loads(store.artifact(rec, "dom_blocks").read_text(encoding="utf-8"))
    assert [b["text"] for b in blocks] == ["Olá, mock", "Clique"]
    assert blocks[0]["color"] == [29, 78, 216] and blocks[0]["font_size"] == 24
    css = json.loads(store.artifact(rec, "css_snapshot").read_text(encoding="utf-8"))
    assert {"elements", "rules", "sheets", "viewport"} <= set(css)
    assert any(e["tag"] == "h1" for e in css["elements"])
    assert any("text-2xl" in e["classes"] for e in css["elements"])  # classe do Tailwind aplicada
    assert rec.technical.console_error_count == 0 and rec.technical.blocked_requests == []
    assert set(rec.technical.axe_violations) >= {"critical", "serious", "moderate", "minor"}
    # retomada: rodar de novo não refaz nada
    assert run_experiment(cfg).skipped == 1


def test_mock_broken_bundle_is_nonexecutable_with_build_errors(repo_root, tmp_path):
    cfg = _cfg(repo_root, tmp_path, "broken")
    assert run_experiment(cfg).by_status == {"nonexecutable": 1}
    (rec,) = RunStore(cfg.path("results_dir"), "main").load_records()
    assert rec.exec.build_ok is False and rec.exec.executable is False
    assert rec.exec.build_error_messages and rec.technical is None


def test_results_are_portable_relative_paths(repo_root, tmp_path):
    cfg = _cfg(repo_root, tmp_path, "ok")
    run_experiment(cfg)
    raw = next((tmp_path / "results" / "runs").glob("*/record.json")).read_text(encoding="utf-8")
    assert str(tmp_path).replace("\\", "\\\\") not in raw
    assert "brennotc" not in raw  # nenhum caminho absoluto com o usuário vaza para o record
