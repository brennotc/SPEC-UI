"""scripts/fetch_figma.py: a única chamada à API. A rede é sempre simulada."""

import importlib.util
import json
import shutil
import urllib.error

import pytest


@pytest.fixture
def fig(repo_root, tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("fetch_figma", repo_root / "scripts" / "fetch_figma.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "easy").mkdir(parents=True)
    shutil.copyfile(repo_root / "benchmarks" / "tasks" / "easy" / "easy_pomodoro.png", tasks_dir / "easy" / "easy_pomodoro.png")
    frames = tasks_dir / "figma_frames.yaml"
    frames.write_text("frames:\n  easy_pomodoro: {node_id: '12:345', png: easy/easy_pomodoro.png}\n", encoding="utf-8")
    out = tmp_path / "figma" / "nodes.raw.json"
    sample = json.loads((repo_root / "tests" / "fixtures" / "figma_nodes_sample.json").read_text(encoding="utf-8"))
    # a API devolve, além de `nodes`, metadados do arquivo e uma thumbnail pré-assinada: nada disso pode ser gravado
    sample |= {"thumbnailUrl": "https://s3.example/x?X-Amz-Credential=AKIAFAKE&X-Amz-Signature=abc", "role": "owner", "version": "1"}
    body = json.dumps(sample).encode()

    monkeypatch.setenv("FIGMA_TOKEN", "tok-secreto")
    monkeypatch.setenv("FIGMA_FILE_KEY", "ABC123")
    monkeypatch.delenv("CI", raising=False)
    calls: list[tuple[str, str]] = []

    def fake_fetch(url, token, timeout=60):
        calls.append((url, token))
        return body

    monkeypatch.setattr(module, "fetch", fake_fetch)
    module.calls, module.body = calls, body
    module.args = ["--frames", str(frames), "--out", str(out)]
    module.out, module.frames = out, frames
    return module


def test_success_makes_exactly_one_request_and_derives_blocks(fig, capsys):
    assert fig.main(fig.args) == 0
    assert len(fig.calls) == 1  # UMA requisição
    url, token = fig.calls[0]
    assert url == "https://api.figma.com/v1/files/ABC123/nodes?ids=12:345" and token == "tok-secreto"
    raw = fig.out.read_text(encoding="utf-8")
    saved = json.loads(raw)
    assert list(saved) == ["nodes"] and saved["nodes"] == json.loads(fig.body)["nodes"]  # só `nodes`, intocado
    assert "X-Amz" not in raw and "AKIA" not in raw and "thumbnailUrl" not in raw and "owner" not in raw
    meta = json.loads((fig.out.parent / "nodes.meta.json").read_text(encoding="utf-8"))
    assert meta["node_ids"] == ["12:345"] and meta["file_key_sha256_12"] != "ABC123" and meta["kept_keys"] == ["nodes"]
    assert meta["bytes"] == len(fig.out.read_bytes())
    assert "ABC123" not in json.dumps(meta) and "tok-secreto" not in json.dumps(meta)
    blocks = json.loads((fig.out.parent / "blocks.json").read_text(encoding="utf-8"))
    assert len(blocks["easy_pomodoro"]["blocks"]) == 6
    assert "easy_pomodoro (6 blocos)" in capsys.readouterr().out


def test_dry_run_never_touches_the_network(fig, capsys):
    assert fig.main([*fig.args, "--dry-run"]) == 0
    assert fig.calls == [] and not fig.out.exists()
    out = capsys.readouterr().out
    assert "ids=12:345" in out and "nenhuma requisição" in out and "tok-secreto" not in out


def test_refuses_to_overwrite_without_force(fig, capsys):
    fig.out.parent.mkdir(parents=True)
    fig.out.write_text("{}", encoding="utf-8")
    assert fig.main(fig.args) == 1
    assert fig.calls == [] and fig.out.read_text(encoding="utf-8") == "{}"
    assert "--force" in capsys.readouterr().err
    assert fig.main([*fig.args, "--force"]) == 0 and len(fig.calls) == 1


def test_refuses_in_ci(fig, monkeypatch, capsys):
    monkeypatch.setenv("CI", "true")
    assert fig.main(fig.args) == 1 and fig.calls == []
    assert "CI" in capsys.readouterr().err


def test_pending_node_ids_stop_before_any_request(fig, capsys):
    fig.frames.write_text("frames:\n  easy_pomodoro: {node_id: TODO, png: easy/easy_pomodoro.png}\n", encoding="utf-8")
    assert fig.main(fig.args) == 2 and fig.calls == []
    assert "easy_pomodoro" in capsys.readouterr().err


@pytest.mark.parametrize("missing", ["FIGMA_TOKEN", "FIGMA_FILE_KEY"])
def test_missing_credentials(fig, monkeypatch, missing):
    monkeypatch.setenv(missing, "")
    assert fig.main(fig.args) == 2 and fig.calls == []


def test_rate_limit_is_reported_with_a_hint(fig, monkeypatch, capsys):
    def limited(url, token, timeout=60):
        raise urllib.error.HTTPError(url, 429, "Too Many Requests", {}, None)

    monkeypatch.setattr(fig, "fetch", limited)
    assert fig.main(fig.args) == 1
    assert "Starter" in capsys.readouterr().err and not fig.out.exists()


def test_missing_node_in_response_saves_raw_but_fails(fig, monkeypatch, capsys):
    monkeypatch.setattr(fig, "fetch", lambda url, token, timeout=60: json.dumps({"nodes": {}}).encode())
    assert fig.main(fig.args) == 1
    assert fig.out.exists()  # a chamada já foi gasta: a resposta fica salva
    assert "ausentes" in capsys.readouterr().err
