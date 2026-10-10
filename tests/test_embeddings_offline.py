"""Modelos de embedding só do cache local: ausência é ConfigurationError legível, nunca tráfego para o Hub (rápido, sem torch)."""

import pytest

from specui.llm import ConfigurationError
from specui.metrics import embeddings as emb


def _cache(root, model, sha, ref=True):
    folder = root / f"models--{model.replace('/', '--')}"
    (folder / "snapshots" / sha).mkdir(parents=True)
    (folder / "snapshots" / sha / "config.json").write_text("{}", encoding="utf-8")
    if ref:
        (folder / "refs").mkdir()
        (folder / "refs" / "main").write_text(sha + "\n", encoding="utf-8")


def test_empty_cache_names_the_model_and_the_expected_folder(tmp_path):
    with pytest.raises(ConfigurationError) as caught:
        emb.model_snapshot(emb.DINOV2_MODEL, tmp_path)
    message = str(caught.value)
    assert emb.DINOV2_MODEL in message and str(tmp_path / "models--facebook--dinov2-base") in message
    assert "não acessa o Hub" in message and "snapshot_download" in message  # diz como baixar uma vez


def test_snapshot_sha_comes_from_refs_main_even_with_several_snapshots(tmp_path):
    _cache(tmp_path, emb.CLIP_MODEL, "aaa111")
    (tmp_path / "models--openai--clip-vit-base-patch32" / "snapshots" / "bbb222").mkdir()
    assert emb.model_snapshot(emb.CLIP_MODEL, tmp_path) == "aaa111"
    assert emb.model_version(emb.CLIP_MODEL, tmp_path) == "openai/clip-vit-base-patch32@aaa111"


def test_single_snapshot_without_refs_is_used_and_an_empty_one_is_refused(tmp_path):
    _cache(tmp_path, emb.DINOV2_MODEL, "ccc333", ref=False)
    assert emb.model_snapshot(emb.DINOV2_MODEL, tmp_path) == "ccc333"
    (tmp_path / "models--openai--clip-vit-base-patch32" / "snapshots" / "ddd444").mkdir(parents=True)
    with pytest.raises(ConfigurationError, match="clip-vit-base-patch32"):
        emb.model_snapshot(emb.CLIP_MODEL, tmp_path)  # pasta de snapshot vazia (download interrompido) não vale


def test_ensure_cached_fails_on_the_first_missing_model(tmp_path):
    _cache(tmp_path, emb.DINOV2_MODEL, "eee555")
    with pytest.raises(ConfigurationError, match="openai/clip-vit-base-patch32"):
        emb.ensure_cached(tmp_path)
    _cache(tmp_path, emb.CLIP_MODEL, "fff666")
    assert emb.ensure_cached(tmp_path) == {emb.DINOV2_MODEL: "eee555", emb.CLIP_MODEL: "fff666"}


def test_importing_the_module_keeps_the_hub_offline():
    import os

    assert os.environ.get("HF_HUB_OFFLINE") == "1"


def test_loading_a_model_missing_from_the_cache_raises_before_touching_the_hub(tmp_path):
    emb._dinov2.cache_clear()
    with pytest.raises(ConfigurationError, match="dinov2-base"):
        emb._dinov2(str(tmp_path))
