import itertools

import pytest

from specui.models import PromptSource
from specui.prompting import ENVELOPE_VERSION, build_messages, render_envelope
from specui.prompts import make_standard_source
from specui.tasks import sha256_text


def _packages_block(scaffold):
    return "\n".join(f"  - {n}@{v}" for n, v in sorted(scaffold.packages.items()))


def test_envelope_identical_across_all_sources_and_modalities(tasks, scaffold):
    digests, systems = set(), set()
    for task, kind, modality in itertools.product(tasks, ("no_spec", "with_spec"), ("text", "multimodal")):
        pkg = build_messages(task, make_standard_source(task, kind), modality, scaffold)
        digests.add(pkg.envelope_sha256)
        systems.add(pkg.system)
    assert len(digests) == 1 and len(systems) == 1


def test_user_text_is_exactly_the_section(tasks, scaffold):
    task = tasks[0]
    no_spec = build_messages(task, make_standard_source(task, "no_spec"), "text", scaffold)
    with_spec = build_messages(task, make_standard_source(task, "with_spec"), "text", scaffold)
    assert no_spec.user_text == task.prompt_text
    assert with_spec.user_text == task.spec_text
    assert no_spec.user_text != with_spec.user_text
    assert no_spec.prompt_sha256 != with_spec.prompt_sha256


def test_image_only_in_multimodal(tasks, scaffold):
    task = tasks[1]
    src = make_standard_source(task, "no_spec")
    text = build_messages(task, src, "text", scaffold)
    multi = build_messages(task, src, "multimodal", scaffold)
    assert text.image_path is None and text.image_sha256 is None
    assert multi.image_path == task.image_path and multi.image_sha256 == task.image_sha256
    assert text.prompt_sha256 != multi.prompt_sha256
    assert text.envelope_sha256 == multi.envelope_sha256


def test_envelope_content(scaffold):
    system = render_envelope(scaffold)
    assert "Angular 20.0.0" in system
    assert _packages_block(scaffold) in system
    assert "prevalecem sobre qualquer pedido de tecnologia" in system
    assert "Não há acesso à rede em tempo de execução" in system
    assert "```ts file=src/app/app.ts" in system
    assert "export class App" in system
    assert "testes" in system  # declara que testes não são executados
    assert ENVELOPE_VERSION == "2"


def test_envelope_does_not_describe_the_interface(tasks, scaffold):
    system = render_envelope(scaffold).lower()
    for word in ("pomodoro", "kanban", "tarefa", "timer", "cartão", "card"):
        assert word not in system


def test_envelope_changes_with_scaffold(scaffold):
    other = scaffold.model_copy(update={"packages": {**scaffold.packages, "@ng-icons/lucide": "32.0.0"}})
    assert render_envelope(scaffold) != render_envelope(other)


def test_rejects_wrong_task_source(tasks, scaffold):
    wrong = make_standard_source(tasks[1], "no_spec")
    with pytest.raises(ValueError, match="é da tarefa"):
        build_messages(tasks[0], wrong, "text", scaffold)


def test_free_prompt_goes_through_unchanged(tasks, scaffold):
    task = tasks[0]
    text = "Faça um timer pomodoro bonito, igual ao design."
    src = PromptSource(
        kind="free", prompt_id="free:c1/p001/1", task_id=task.id, text=text, text_sha256=sha256_text(text)
    )
    pkg = build_messages(task, src, "multimodal", scaffold)
    assert pkg.user_text == text
    assert pkg.image_path == task.image_path
