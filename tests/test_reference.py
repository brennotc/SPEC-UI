import json
import shutil

import pytest

from specui.metrics.reference import (
    ReferenceUnavailableError,
    derive_all,
    derive_blocks,
    load_reference_blocks,
    normalize_text,
    ocr_blocks,
)


@pytest.fixture
def nodes(repo_root):
    return json.loads((repo_root / "tests" / "fixtures" / "figma_nodes_sample.json").read_text(encoding="utf-8"))


def test_derive_blocks_uses_frame_origin_visibility_and_colors(nodes):
    blocks, frame = derive_blocks(nodes, "12:345", (1440, 900))
    assert frame["width"] == 1440
    assert [b.text for b in blocks] == [
        "Pomodoro", "Foco Total", "25:00", "Gradiente", "Texto em duas linhas", "Espaços extras",
    ]
    by_text = {b.text: b for b in blocks}
    # coordenadas relativas à origem do frame (1000, 500), não do canvas
    p = by_text["Pomodoro"]
    assert (p.x0, p.y0, p.x1, p.y1) == (80.0, 20.0, 220.0, 50.0)
    assert p.color_rgb == (255, 255, 255) and p.font_size == 28
    assert by_text["Foco Total"].color_rgb == (215, 71, 71)
    assert by_text["Gradiente"].color_rgb is None  # preenchimento não sólido
    # excluídos: camada oculta, fora do frame, texto vazio
    assert not {"OCULTO", "FORA", ""} & {b.text for b in blocks}
    assert all(b.source == "figma" for b in blocks)


def test_derive_blocks_normalizes_whitespace_and_newlines(nodes):
    blocks, _ = derive_blocks(nodes, "12:345", (1440, 900))
    assert {b.text for b in blocks} >= {"Texto em duas linhas", "Espaços extras"}
    assert normalize_text("  a \n b\t c ") == "a b c"


@pytest.mark.parametrize("size", [(2880, 1800), (1440, 800), (720, 450)])
def test_derive_blocks_rejects_png_not_in_1x(nodes, size):
    with pytest.raises(ReferenceUnavailableError, match="1x"):
        derive_blocks(nodes, "12:345", size)


def test_derive_blocks_missing_node(nodes):
    with pytest.raises(ReferenceUnavailableError, match="ausente"):
        derive_blocks(nodes, "9:9", (1440, 900))


def test_derive_all_writes_blocks_json_and_skips_todo(repo_root, nodes, tmp_path):
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "easy").mkdir(parents=True)
    shutil.copyfile(repo_root / "benchmarks" / "tasks" / "easy" / "easy_pomodoro.png", tasks_dir / "easy" / "easy_pomodoro.png")
    frames = tasks_dir / "figma_frames.yaml"
    frames.write_text(
        "frames:\n  easy_pomodoro: {node_id: '12:345', png: easy/easy_pomodoro.png}\n"
        "  hard_kanban: {node_id: TODO, png: hard/hard_kanban.png}\n", encoding="utf-8")
    raw, out = tmp_path / "nodes.raw.json", tmp_path / "blocks.json"
    raw.write_text(json.dumps(nodes), encoding="utf-8")
    result = derive_all(frames, raw, out, tasks_dir)
    assert set(result) == {"easy_pomodoro"}  # TODO é pulado
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["easy_pomodoro"]["node_id"] == "12:345" and len(saved["easy_pomodoro"]["blocks"]) == 6


def test_load_reference_blocks_precedence(tasks, nodes, tmp_path):
    task = tasks[0].model_copy(update={"figma_node_id": "12:345"})
    refs = tmp_path / "figma"
    refs.mkdir()
    # 1. nada disponível
    with pytest.raises(ReferenceUnavailableError, match="sem referência do Figma"):
        load_reference_blocks(task, refs)
    # 2. só o JSON bruto: deriva na hora
    (refs / "nodes.raw.json").write_text(json.dumps(nodes), encoding="utf-8")
    blocks, source = load_reference_blocks(task, refs)
    assert source == "figma" and len(blocks) == 6
    # 3. blocks.json tem prioridade sobre o JSON bruto
    (refs / "blocks.json").write_text(json.dumps({task.id: {"blocks": [
        {"text": "só este", "x0": 0, "y0": 0, "x1": 10, "y1": 10}]}}), encoding="utf-8")
    blocks, source = load_reference_blocks(task, refs)
    assert [b.text for b in blocks] == ["só este"] and source == "figma"


def test_without_node_id_and_without_ocr_there_is_no_reference(tasks, nodes, tmp_path):
    (tmp_path / "nodes.raw.json").write_text(json.dumps(nodes), encoding="utf-8")
    task = tasks[0].model_copy(update={"figma_node_id": None})
    with pytest.raises(ReferenceUnavailableError):
        load_reference_blocks(task, tmp_path)


def test_ocr_fallback_reports_missing_dependency(tasks, tmp_path):
    try:
        import easyocr  # noqa: F401
    except ImportError:
        with pytest.raises(ReferenceUnavailableError, match="requirements-ocr"):
            ocr_blocks(tasks[0].image_path)
        with pytest.raises(ReferenceUnavailableError, match="requirements-ocr"):
            load_reference_blocks(tasks[0], tmp_path, allow_ocr=True)
    else:  # pragma: no cover - ambiente com easyocr instalado
        pytest.skip("easyocr instalado")
