import pytest

from specui.metrics.input_spec import (
    compute_input_spec,
    constraint_density,
    image_references,
    requirement_coverage,
    stack_requests,
    structure_markers,
)


def test_constraint_density_counts_explicit_constraints():
    text = "Fundo #D7CFCF e #fff, header de 70px e 503 px; default 25. aria-label e <header> <input type='text'>"
    d = constraint_density(text)
    assert d["hex"] == 2
    assert d["px"] == 2
    assert d["defaults"] == 1
    assert d["aria"] == 1
    assert d["html_tags"] == 2


def test_spec_is_denser_than_prompt(tasks):
    for t in tasks:
        prompt, spec = constraint_density(t.prompt_text), constraint_density(t.spec_text)
        assert sum(spec.values()) > sum(prompt.values())
        assert spec["hex"] > 0 and spec["px"] > 0


def test_structure_markers():
    text = "# Título\n- a\n- b\n1. um\n2. dois\n```ts\ntype X = 1\n```\ninterface Foo {}\n"
    m = structure_markers(text)
    assert m["headings"] == 1
    assert m["lists"] == 2
    assert m["numbering"] == 2
    assert m["code_blocks"] == 1
    assert m["type_decls"] == 2


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Faça igual ao design do Figma", 2),  # "igual ao design" + "do Figma"
        ("como na imagem anexa", 1),  # expressões sobrepostas contam uma vez
        ("Construa um timer com borda vermelha", 0),
    ],
)
def test_image_references(text, expected):
    assert image_references(text) == expected


@pytest.mark.parametrize(
    "text, field",
    [
        ("Use React com hooks", "react"),
        ("Crie em HTML puro", "html_puro"),
        ("só HTML e sem frameworks", "html_puro"),
        ("com Bootstrap 5", "bootstrap"),
        ("usando Vue 3", "vue"),
        ("com jQuery", "jquery"),
        ("em Next.js", "next"),
        ("com Svelte", "svelte"),
    ],
)
def test_stack_requests_detects_other_technologies(text, field):
    s = stack_requests(text)
    assert getattr(s, field) is True
    assert s.any is True


def test_stack_requests_no_false_positive_on_the_real_tasks(tasks):
    for t in tasks:
        assert stack_requests(t.prompt_text).any is False, t.id
        # a spec cita Angular/Tailwind (a stack certa): não é pedido de outra stack
        assert stack_requests(t.spec_text).any is False, t.id


def test_stack_requests_other_libraries():
    s = stack_requests("estilo com Material UI e styled-components")
    assert set(s.outros) == {"material_ui", "styled_components"}
    assert s.any is True


def test_requirement_coverage_by_info_source():
    reqs = [
        {"id": "E-01", "info_source": "image", "mention_patterns": [r"fundo\s+branco"]},
        {"id": "E-02", "info_source": "image", "mention_patterns": [r"header"]},
        {"id": "E-07", "info_source": "behavior", "mention_patterns": [r"play|pause"]},
        {"id": "E-09", "info_source": "behavior", "mention_patterns": [r"25\s*minutos"]},
        {"id": "X", "info_source": "spec_only", "mention_patterns": []},  # sem padrão: não conta
    ]
    cov = requirement_coverage("Um timer com fundo branco e botão de play", reqs)
    assert cov.total == pytest.approx(2 / 4)
    assert cov.by_info_source == {"image": 0.5, "behavior": 0.5}


def test_requirement_coverage_empty_is_none():
    assert requirement_coverage("qualquer", []).total is None


def test_compute_input_spec_end_to_end(tasks):
    easy = tasks[0]
    m = compute_input_spec(easy.spec_text, envelope_chars=1234)
    assert m.chars == len(easy.spec_text)
    assert m.words > 100
    assert m.structure_markers["code_blocks"] >= 1
    assert m.envelope_chars == 1234
    assert m.stack_requests.any is False
    assert compute_input_spec(easy.prompt_text).chars < m.chars


def test_mention_patterns_cover_both_texts_of_every_task(repo_root):
    """`with_spec` é a referência de 'cobertura total': todo requisito com padrão tem de ser citado pela spec; e todo requisito
    testável a partir do prompt (categorias a e c) tem de ser citado pelo prompt. Os da spec (categoria s) não precisam estar
    no prompt: é justamente o que ele não diz."""
    import re

    from specui.oracle.requirements import load_requirements
    from specui.tasks import load_tasks

    for task in load_tasks(repo_root / "benchmarks"):
        reqs = [r for r in load_requirements(repo_root / "oracles", task.id) if r.mention_patterns]

        def missed(text, selection):
            return [r.id for r in selection if not any(re.search(p, text, re.IGNORECASE) for p in r.mention_patterns)]

        assert missed(task.spec_text, reqs) == [], (task.id, "spec")
        assert missed(task.prompt_text, [r for r in reqs if r.category in ("a", "c")]) == [], (task.id, "prompt")
        assert requirement_coverage(task.spec_text, reqs).total == 1.0
