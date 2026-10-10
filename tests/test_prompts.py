import json
import textwrap

import pytest

from specui.config import load_config
from specui.prompts import (
    import_free_prompts,
    load_free_sources,
    make_standard_source,
    redact_pii,
    resolve_prompt_sources,
)

TASK_IDS = {"easy_pomodoro", "medium_tarefas", "hard_kanban"}


def test_standard_sources_are_the_two_sections(tasks):
    for t in tasks:
        no_spec, with_spec = make_standard_source(t, "no_spec"), make_standard_source(t, "with_spec")
        assert (no_spec.text, with_spec.text) == (t.prompt_text, t.spec_text)
        assert no_spec.prompt_id == f"{t.id}/no_spec"
        assert no_spec.text_sha256 != with_spec.text_sha256


def test_resolve_prompt_sources_default(repo_root, tasks):
    cfg = load_config(repo_root / "configs" / "default.yaml")
    sources = resolve_prompt_sources(cfg, tasks)
    assert len(sources) == 6  # 3 tarefas x {no_spec, with_spec}
    assert {s.kind for s in sources} == {"no_spec", "with_spec"}


# ------------------------------------------------------------------- PII


def test_redact_pii_categories():
    text = (
        "Meu nome é Maria Souza e meu email é maria.souza@exemplo.com. "
        "Telefone (21) 99999-8888, CPF 123.456.789-09, veja linkedin.com/in/maria-souza. "
        "Fale com Joãozinho."
    )
    clean, found = redact_pii(text, redact_terms=["Joãozinho"])
    for secret in ("Maria Souza", "maria.souza", "99999-8888", "123.456.789-09", "linkedin.com/in", "Joãozinho"):
        assert secret not in clean
    assert {c for c, _ in found} == {"nome", "email", "telefone", "cpf", "url_perfil", "termo"}
    assert "Meu nome é [NOME]" in clean


def test_redact_pii_keeps_design_numbers():
    text = "Círculo de 503px X 503px, header de 70px, tempo 25:00, cor #D7CFCF, 1440x900"
    clean, found = redact_pii(text)
    assert clean == text and found == []


# ------------------------------------------------------------------- importador


def _collection(tmp_path, anonymous=True, informed=True):
    d = tmp_path / "coleta_teste"
    d.mkdir()
    (d / "collection.yaml").write_text(
        f"anonymous: {str(anonymous).lower()}\nparticipants_informed: {str(informed).lower()}\n"
        "instrument_version: '1'\nmaterial_shown: image\n",
        encoding="utf-8",
    )
    return d


MAP_WIDE = textwrap.dedent(
    """\
    min_chars: 20
    columns:
      task_columns:
        easy_pomodoro: "Prompt Pomodoro"
        hard_kanban: "Prompt Kanban"
      intended_modality: "Modelo vê a imagem?"
      collected_at: "Carimbo"
    profile:
      frontend_experience: "Front-end"
    profile_bands:
      frontend_experience: [nenhuma, iniciante, avancada]
    modality_values: {"Sim": multimodal, "Não": text}
    drop: ["Nome", "E-mail"]
    redact_terms: ["Fulano"]
    """
)

CSV_WIDE = (
    "Carimbo,Nome,E-mail,Modelo vê a imagem?,Front-end,Prompt Pomodoro,Prompt Kanban\n"
    "2026-11-03 14:22:10,Ana Lima,ana@x.com,Sim,iniciante,"
    '"Faça um timer pomodoro igual à imagem. Meu nome é Ana Lima.",'
    '"Quadro kanban com 4 colunas, igual ao design"\n'
    "04/11/2026 09:00,Beto,beto@x.com,Não,avancada,"
    '"Faça um timer pomodoro igual à imagem. Meu nome é Ana Lima.",'  # duplicado após PII
    ',\n'
    "2026-11-05 10:00,Caio,caio@x.com,Sim,especialista,Pomodoro com fundo branco e header vermelho,\n"
    "2026-11-06 10:00,Duda,duda@x.com,Sim,nenhuma,curto,\n"
)


def _write(tmp_path, csv_text=CSV_WIDE, map_text=MAP_WIDE):
    csv_path, map_path = tmp_path / "respostas.csv", tmp_path / "map.yaml"
    csv_path.write_text(csv_text, encoding="utf-8")
    map_path.write_text(map_text, encoding="utf-8")
    return csv_path, map_path


def test_import_requires_anonymous_and_informed(tmp_path):
    csv_path, map_path = _write(tmp_path)
    with pytest.raises(ValueError, match="anonymous"):
        import_free_prompts(_collection(tmp_path, anonymous=False), csv_path, map_path, TASK_IDS)
    other = tmp_path / "outra"
    other.mkdir()
    (other / "collection.yaml").write_text("anonymous: true\nparticipants_informed: false\n", encoding="utf-8")
    with pytest.raises(ValueError, match="participants_informed"):
        import_free_prompts(other, csv_path, map_path, TASK_IDS)


def test_import_wide_format_anonymizes_and_validates(tmp_path):
    coll = _collection(tmp_path)
    csv_path, map_path = _write(tmp_path)
    res = import_free_prompts(coll, csv_path, map_path, TASK_IDS)

    # só Ana (2 prompts) é aceita; Beto duplica o texto de Ana e sai sem prompts;
    # Caio tem faixa fora do permitido; Duda é curto demais.
    assert [(r["participant_id"], r["task_id"]) for r in res.accepted] == [
        ("p001", "easy_pomodoro"),
        ("p001", "hard_kanban"),
    ]
    reasons = sorted(r["reason"] for r in res.rejected)
    assert reasons == ["duplicate", "profile_out_of_band:frontend_experience", "too_short"]

    first = res.accepted[0]
    assert first["intended_modality"] == "multimodal"
    assert first["collected_at"] == "2026-11-03"  # hora removida
    assert first["profile"] == {"frontend_experience": "iniciante"}
    assert "Ana Lima" not in first["text"] and "[NOME]" in first["text"]
    assert res.ignored_columns == ["Nome", "E-mail"]

    # nada identificável chega ao disco
    jsonl = (coll / "prompts.jsonl").read_text(encoding="utf-8")
    report = (coll / "import_report.md").read_text(encoding="utf-8")
    for secret in ("Ana", "Lima", "ana@x.com", "beto", "Caio", "Duda", "14:22:10"):
        assert secret not in jsonl, secret
        assert secret not in report, secret
    assert "nome" in report and "p001" not in report  # remoção listada; ids só no jsonl
    assert not (coll / "identity_map.csv").exists()


def test_import_rejects_mapped_drop_columns_and_missing_columns(tmp_path):
    coll = _collection(tmp_path)
    csv_path, map_path = _write(tmp_path, map_text=MAP_WIDE.replace('drop: ["Nome", "E-mail"]', 'drop: ["Front-end"]'))
    with pytest.raises(ValueError, match="também estão em 'drop'"):
        import_free_prompts(coll, csv_path, map_path, TASK_IDS)
    csv_path, map_path = _write(tmp_path, csv_text="a,b\n1,2\n")
    with pytest.raises(ValueError, match="ausentes no CSV"):
        import_free_prompts(coll, csv_path, map_path, TASK_IDS)


def test_import_long_format_gives_one_participant_per_row(tmp_path):
    coll = _collection(tmp_path)
    map_text = textwrap.dedent(
        """\
        columns: {task: "Tarefa", text: "Prompt"}
        task_values: {"Pomodoro": easy_pomodoro, "Kanban": hard_kanban, "Outra": inexistente}
        """
    )
    csv_text = (
        "Tarefa,Prompt\n"
        "Pomodoro,Um timer pomodoro com fundo branco e header vermelho\n"
        "Kanban,Quadro kanban com quatro colunas coloridas e cards\n"
        "Outra,Algo que não existe como tarefa no benchmark\n"
        "Pomodoro,\n"
    )
    csv_path, map_path = _write(tmp_path, csv_text, map_text)
    res = import_free_prompts(coll, csv_path, map_path, TASK_IDS)
    assert [r["participant_id"] for r in res.accepted] == ["p001", "p002"]
    assert sorted(r["reason"] for r in res.rejected) == ["empty", "unknown_task"]


def test_load_free_sources_roundtrip(tmp_path, tasks):
    bench = tmp_path / "benchmarks"
    coll = bench / "free_prompts" / "c1"
    coll.mkdir(parents=True)
    (coll / "collection.yaml").write_text(
        "anonymous: true\nparticipants_informed: true\ninstrument_version: v2\nmaterial_shown: image+brief\n",
        encoding="utf-8",
    )
    rec = {
        "participant_id": "p007", "task_id": "easy_pomodoro", "n": 1, "text": "Um timer simples",
        "text_sha256": "abc", "intended_modality": "text", "collected_at": "2026-11-03",
        "profile": {"frontend_experience": "iniciante"},
    }
    (coll / "prompts.jsonl").write_text(json.dumps(rec) + "\n" + json.dumps({**rec, "task_id": "x"}) + "\n", encoding="utf-8")
    sources = load_free_sources(bench, "c1", {"easy_pomodoro"})
    assert len(sources) == 1
    s = sources[0]
    assert s.kind == "free" and s.prompt_id == "free:c1/p007/1"
    assert s.material_shown == "image+brief" and s.instrument_version == "v2"
    assert s.intended_modality == "text" and s.metadata == {"frontend_experience": "iniciante"}
