import pytest
from pydantic import ValidationError

from specui.config import config_sha256, load_config
from specui.models import Generator, RunConfig


def test_default_config_loads(repo_root):
    cfg = load_config(repo_root / "configs" / "default.yaml")
    assert cfg.run_kind == "main"
    assert cfg.repetitions == 5
    assert [g.provider for g in cfg.generators] == ["google"]
    assert all(g.temperature is None for g in cfg.generators)
    assert cfg.analysis.equivalence_margin is None
    assert cfg.path("benchmarks_dir") == (repo_root / "benchmarks").resolve()


def test_pilot_extends_default(repo_root):
    default = load_config(repo_root / "configs" / "default.yaml")
    pilot = load_config(repo_root / "configs" / "pilot.yaml")
    assert pilot.run_kind == "pilot"
    assert pilot.repetitions == 1
    assert pilot.free_repetitions == 1
    # tudo o mais é herdado: mesmos geradores e mesmo harness
    assert pilot.generators == default.generators
    assert pilot.build_timeout_s == default.build_timeout_s
    assert config_sha256(pilot) != config_sha256(default)


def test_overrides_merge_over_yaml(repo_root):
    cfg = load_config(
        repo_root / "configs" / "default.yaml",
        overrides={"repetitions": 2, "analysis": {"equivalence_margin": 0.1}},
    )
    assert cfg.repetitions == 2
    assert cfg.analysis.equivalence_margin == 0.1
    assert cfg.analysis.n_boot == 10_000  # mesclado, não substituído


def test_config_sha_is_stable_and_root_independent(repo_root):
    a = load_config(repo_root / "configs" / "default.yaml")
    b = a.model_copy(update={"repo_root": "/outro/lugar"})
    assert config_sha256(a) == config_sha256(b)


def test_extends_cycle_is_detected(tmp_path):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    (tmp_path / "a.yaml").write_text("extends: b.yaml\n", encoding="utf-8")
    (tmp_path / "b.yaml").write_text("extends: a.yaml\n", encoding="utf-8")
    with pytest.raises(ValueError, match="ciclo"):
        load_config(tmp_path / "a.yaml", repo_root=tmp_path)


@pytest.mark.parametrize("model_id", ["gemini-flash-latest", "gemini-3-pro-preview", "foo-exp"])
def test_aliases_are_rejected(model_id):
    with pytest.raises(ValidationError, match="alias"):
        Generator(provider="google", model_id=model_id)


def test_alias_allowed_for_mock():
    Generator(provider="mock", model_id="mock-latest")


def test_temperature_zero_is_rejected():
    with pytest.raises(ValidationError, match="nunca 0"):
        Generator(provider="google", model_id="gemini-2.5-flash", temperature=0.0)


def test_duplicate_generators_and_bad_sources_are_rejected():
    gen = {"provider": "google", "model_id": "gemini-2.5-flash"}
    with pytest.raises(ValidationError, match="repetidos"):
        RunConfig(generators=[gen, gen])
    with pytest.raises(ValidationError, match="inválida"):
        RunConfig(generators=[gen], prompt_sources=["no_spec", "livre"])
    with pytest.raises(ValidationError):
        RunConfig(generators=[])
    RunConfig(generators=[gen], prompt_sources=["no_spec", "with_spec", "free:coleta_2026_11"])


def test_python_requirement_matches_what_the_code_uses(repo_root):
    """O harness usa `os.path.isjunction` (Python 3.12): o pacote não pode declarar uma versão menor."""
    import os
    import tomllib

    declared = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["requires-python"]
    assert declared == ">=3.12" and hasattr(os.path, "isjunction")


def test_workspace_dir_default_depends_on_the_platform(monkeypatch):
    from specui import models

    monkeypatch.setattr(models.os, "name", "nt")
    assert models.default_workspace_dir() == "C:/specui-work"
    monkeypatch.setattr(models.os, "name", "posix")
    assert models.default_workspace_dir() == "~/.cache/specui-work"  # nunca "C:/..." (seria relativo e cairia dentro do repo)
    assert not models.RunConfig.model_fields["workspace_dir"].is_required()


def test_default_yaml_does_not_pin_a_windows_workspace(repo_root):
    lines = (repo_root / "configs" / "default.yaml").read_text(encoding="utf-8").splitlines()
    assert not [line for line in lines if line.startswith("workspace_dir:")]  # comentários não contam


def test_playwright_is_pinned_and_the_lock_agrees(repo_root):
    """A versão do Playwright define o Chromium (render, métricas visuais, cores do oráculo): precisa ser exata."""
    req = (repo_root / "requirements.txt").read_text(encoding="utf-8")
    pinned = [line for line in req.splitlines() if line.startswith("playwright==")]
    assert len(pinned) == 1
    version = pinned[0].split("==")[1].split()[0]
    lock = (repo_root / "requirements.lock").read_text(encoding="utf-8").splitlines()
    assert f"playwright=={version}" in lock
    assert not any(line.startswith("specui") for line in lock)


def test_config_hash_ignores_machine_paths_but_not_experiment_parameters(repo_root, tmp_path):
    base = load_config(repo_root / "configs" / "default.yaml", overrides={"results_dir": str(tmp_path / "a")})
    elsewhere = load_config(repo_root / "configs" / "default.yaml", overrides={
        "results_dir": str(tmp_path / "b"), "workspace_dir": str(tmp_path / "ws"), "model_cache_dir": str(tmp_path / "hf")})
    assert config_sha256(base) == config_sha256(elsewhere)
    assert config_sha256(base) != config_sha256(load_config(repo_root / "configs" / "default.yaml", overrides={"repetitions": 2}))
    assert config_sha256(base) != config_sha256(load_config(repo_root / "configs" / "default.yaml", overrides={"base_seed": 7}))


def test_the_fixed_clock_has_one_source_and_the_config_cannot_change_it(repo_root):
    from datetime import date

    from oracles.common.dates import TODAY
    from oracles.easy_pomodoro.helpers import PAUSE_AT
    from specui.clock import FIXED_NOW, fixed_date, fixed_plus
    from specui.harness.browser import BrowserSession
    from specui.oracle.runner import FIXED_NOW as RUNNER_NOW

    assert RUNNER_NOW == FIXED_NOW == RunConfig.model_fields["clock_epoch_iso"].default == BrowserSession().clock_epoch_iso
    assert TODAY == fixed_date() == date(2026, 3, 10) and PAUSE_AT == fixed_plus(1) == "2026-03-10T10:01:00"
    assert load_config(repo_root / "configs" / "default.yaml").clock_epoch_iso == FIXED_NOW
    with pytest.raises(ValueError, match="parte do instrumento"):
        load_config(repo_root / "configs" / "default.yaml", overrides={"clock_epoch_iso": "2026-03-11T10:00:00"})


def test_tasks_accept_difficulties_and_ids_and_refuse_nonsense(repo_root):
    ok = load_config(repo_root / "configs" / "default.yaml", overrides={"tasks": ["easy_pomodoro", "hard"]})
    assert ok.tasks == ["easy_pomodoro", "hard"]
    for bad in ([], ["Easy"], ["easy", "easy"], ["../etc"]):
        with pytest.raises(ValueError):
            load_config(repo_root / "configs" / "default.yaml", overrides={"tasks": bad})


def test_task_ids_reach_load_tasks(repo_root):
    from specui.tasks import load_tasks

    cfg = load_config(repo_root / "configs" / "default.yaml", overrides={"tasks": ["hard_kanban"]})
    assert [t.id for t in load_tasks(repo_root / "benchmarks", list(cfg.tasks))] == ["hard_kanban"]
