"""scripts/snapshot_pilot.py: o snapshot do piloto só leva a evidência curada, nunca dist/ nem o run mock."""

import importlib.util
import json

import pytest


@pytest.fixture
def snap(repo_root):
    spec = importlib.util.spec_from_file_location("snapshot_pilot", repo_root / "scripts" / "snapshot_pilot.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pilot(tmp_path):
    root = tmp_path / "pilot"
    lines = []
    for run_id, cell in (("g1", "easy/no_spec|text|google:m|r0"), ("g2", "easy/with_spec|text|google:m|r0"), ("m1", "easy/no_spec|text|mock:mock-1|r0")):
        run = root / "runs" / run_id
        (run / "dist").mkdir(parents=True)
        (run / "generated" / "src").mkdir(parents=True)
        for name in ("record.json", "screenshot.png", "response.raw.txt", "axe.json", "css_snapshot.json", "prompt.user.txt", "build.stdout.txt"):
            (run / name).write_text(name, encoding="utf-8")
        (run / "dist" / "main.js").write_text("x" * 100, encoding="utf-8")
        lines.append(json.dumps({"run_id": run_id, "cell_key": cell, "status": "done"}))
    lines.insert(0, json.dumps({"run_id": "g1-antigo", "cell_key": "easy/no_spec|text|google:m|r0", "status": "api_error"}))
    (root / "manifest.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for name in ("failure_report.md", "failure_report.csv", "sensitivity.csv", "sensitivity_baseline.csv", "outro.txt"):
        (root / name).write_text(name, encoding="utf-8")
    return root


def test_snapshot_copies_only_the_curated_evidence(snap, tmp_path):
    out = tmp_path / "out"
    written = {p.as_posix() for p in snap.snapshot(_pilot(tmp_path), out)}
    assert written == {
        "runs/g1/record.json", "runs/g1/screenshot.png", "runs/g1/response.raw.txt",
        "runs/g2/record.json", "runs/g2/screenshot.png", "runs/g2/response.raw.txt",
        "failure_report.md", "failure_report.csv", "sensitivity.csv", "sensitivity_baseline.csv", "manifest.jsonl",
    }
    assert not any("dist" in p or "generated" in p or "m1" in p or "axe" in p for p in written)  # nem dist, nem mock, nem o resto
    kept = [json.loads(line) for line in (out / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {e["run_id"] for e in kept} == {"g1-antigo", "g1", "g2"}  # o histórico do gerador real fica; o mock sai


def test_snapshot_refuses_dist_paths(snap, tmp_path, monkeypatch):
    root = tmp_path / "pilot"
    (root / "runs" / "g1" / "dist").mkdir(parents=True)
    (root / "runs" / "g1" / "dist" / "main.js").write_text("x", encoding="utf-8")
    entry = json.dumps({"run_id": "g1", "cell_key": "a|b|google:m|r0", "status": "done"})
    (root / "manifest.jsonl").write_text(entry + "\n", encoding="utf-8")
    monkeypatch.setattr(snap, "PER_RUN", ("dist/main.js",))  # um nome que atravessa dist/ tem de ser recusado
    with pytest.raises(ValueError, match="nunca inclui"):
        snap.snapshot(root, tmp_path / "out")
