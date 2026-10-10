import shutil

import pytest

from specui.tasks import load_tasks, png_size, split_sections


def test_loads_three_tasks_in_difficulty_order(tasks):
    assert [t.id for t in tasks] == ["easy_pomodoro", "medium_tarefas", "hard_kanban"]
    assert [t.difficulty for t in tasks] == ["easy", "medium", "hard"]


def test_prompt_and_spec_are_separate_sections(tasks):
    easy = tasks[0]
    assert easy.prompt_text.startswith("Construa um front-end para um timer Pomodoro")
    assert "# 1. ESCOPO" not in easy.prompt_text
    assert easy.spec_text.startswith("# 1. ESCOPO")
    assert "## Specification" not in easy.spec_text
    assert "## Prompt" not in easy.spec_text
    # with_spec NÃO carrega frontmatter nem o prompt
    assert "complexity:" not in easy.spec_text
    assert "Construa um front-end" not in easy.spec_text


def test_images_are_figma_frames_1440x900(tasks):
    for t in tasks:
        assert t.image_size == (1440, 900)
        assert len(t.image_sha256) == 64
        assert png_size(t.image_path) == (1440, 900)


def test_figma_node_ids_use_the_api_format(tasks):
    # figma_frames.yaml: "9:46" (a URL mostra "9-46"); "TODO" vira None
    import re

    assert all(t.figma_node_id is None or re.fullmatch(r"\d+:\d+", t.figma_node_id) for t in tasks)


def test_select_by_difficulty_and_id(repo_root):
    assert [t.id for t in load_tasks(repo_root / "benchmarks", ["hard"])] == ["hard_kanban"]
    assert [t.id for t in load_tasks(repo_root / "benchmarks", ["easy_pomodoro"])] == [
        "easy_pomodoro"
    ]
    with pytest.raises(ValueError, match="desconhecidas"):
        load_tasks(repo_root / "benchmarks", ["nao_existe"])


def test_missing_png_fails_clearly(repo_root, tmp_path):
    bench = tmp_path / "benchmarks"
    shutil.copytree(repo_root / "benchmarks" / "tasks", bench / "tasks")
    (bench / "tasks" / "easy" / "easy_pomodoro.png").unlink()
    with pytest.raises(FileNotFoundError, match="PNG de referência não encontrado"):
        load_tasks(bench)


def test_frontmatter_id_must_match_filename(repo_root, tmp_path):
    bench = tmp_path / "benchmarks"
    shutil.copytree(repo_root / "benchmarks" / "tasks", bench / "tasks")
    md = bench / "tasks" / "easy" / "easy_pomodoro.md"
    md.write_text(md.read_text(encoding="utf-8").replace("id: easy_pomodoro", "id: outro"), encoding="utf-8")
    with pytest.raises(ValueError, match="difere do nome do arquivo"):
        load_tasks(bench)


def test_split_sections_handles_crlf_and_frontmatter():
    md = "---\r\nid: x\r\ncomplexity: Easy\r\n---\r\n## Prompt\r\n\r\nFaça A.\r\n\r\n## Specification\r\n\r\nDetalhe B.\r\n"
    fm, prompt, spec = split_sections(md)
    assert fm == {"id": "x", "complexity": "Easy"}
    assert prompt == "Faça A."
    assert spec == "Detalhe B."


@pytest.mark.parametrize(
    "md, msg",
    [
        ("## Specification\nx", "'## Prompt' não encontrada"),
        ("## Prompt\nx", "'## Specification' não encontrada"),
        ("## Specification\ny\n## Prompt\nx", "antes de"),
        ("## Prompt\n\n## Specification\nx", "'## Prompt' vazia"),
    ],
)
def test_split_sections_errors(md, msg):
    with pytest.raises(ValueError, match=msg):
        split_sections(md)
