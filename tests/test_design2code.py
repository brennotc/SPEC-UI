"""Métricas Design2Code com blocos sintéticos: cada defeito controlado mexe só na métrica certa."""

import numpy as np
import pytest

from specui.metrics.design2code import (
    Block,
    color_similarity,
    compute_design2code,
    inpaint_text,
    match_blocks,
    match_with_merges,
    merge_two,
    text_similarity,
)
from specui.metrics.reference import RefBlock

VIEWPORT = (1440, 900)
SPEC = [  # texto, x, y, w, h, cor
    ("Pomodoro", 80, 20, 140, 30, (255, 255, 255)),
    ("Foco Total", 600, 200, 240, 44, (215, 71, 71)),
    ("25:00", 560, 300, 320, 150, (215, 71, 71)),
    ("Pausa curta", 600, 700, 200, 30, (101, 139, 92)),
]


def refs(spec=SPEC):
    return [RefBlock(text=t, x0=x, y0=y, x1=x + w, y1=y + h, color_rgb=c) for t, x, y, w, h, c in spec]


def doms(spec=SPEC):
    return [{"text": t, "x": x, "y": y, "w": w, "h": h, "color": list(c)} for t, x, y, w, h, c in spec]


def run(ref_spec=SPEC, gen_spec=SPEC):
    return compute_design2code(refs(ref_spec), doms(gen_spec), VIEWPORT)


def test_identical_pages_score_one_everywhere():
    m, details = run()
    assert m.n_ref_blocks == m.n_gen_blocks == m.n_matched == 4
    assert m.block_match == pytest.approx(1.0)
    assert m.text == pytest.approx(1.0) and m.position == pytest.approx(1.0) and m.color == pytest.approx(1.0)
    assert m.n_merged_ref == m.n_merged_gen == 0
    assert len(details["pairs"]) == 4 and not details["unmatched_ref"] and not details["unmatched_gen"]


def test_shifting_blocks_only_lowers_position():
    shifted = [(t, x + 144, y, w, h, c) for t, x, y, w, h, c in SPEC]  # 10% da largura
    m, _ = run(gen_spec=shifted)
    assert m.position == pytest.approx(0.9)
    assert m.block_match == pytest.approx(1.0) and m.text == pytest.approx(1.0) and m.color == pytest.approx(1.0)


def test_recoloring_one_block_only_lowers_color():
    recolored = [(*SPEC[0][:5], (0, 0, 255)), *SPEC[1:]]
    m, _ = run(gen_spec=recolored)
    assert 0 < m.color < 0.99
    assert m.text == pytest.approx(1.0) and m.position == pytest.approx(1.0) and m.block_match == pytest.approx(1.0)


def test_removing_a_block_only_lowers_block_match():
    m, details = run(gen_spec=SPEC[:3])
    assert m.n_matched == 3 and m.text == pytest.approx(1.0) and m.position == pytest.approx(1.0)
    matched = 2 * sum(w * h for _, _, _, w, h, _ in SPEC[:3])
    total = sum(w * h for *_, w, h, _ in SPEC) + sum(w * h for *_, w, h, _ in SPEC[:3])
    assert m.block_match == pytest.approx(matched / total)
    assert [b["text"] for b in details["unmatched_ref"]] == ["Pausa curta"]


def test_extra_generated_block_lowers_block_match_too():
    m, details = run(gen_spec=[*SPEC, ("Lixo", 100, 800, 200, 30, (0, 0, 0))])
    assert m.block_match < 0.99 and m.text == pytest.approx(1.0)
    assert [b["text"] for b in details["unmatched_gen"]] == ["Lixo"]


# ---------------------------------------------------------------- fusão de blocos vizinhos


def test_split_generated_block_is_recovered_by_merging():
    split = [SPEC[0], ("Foco", 600, 200, 80, 44, (215, 71, 71)), ("Total", 690, 200, 150, 44, (215, 71, 71)), *SPEC[2:]]
    m, details = run(gen_spec=split)
    assert m.n_merged_gen == 1 and m.n_merged_ref == 0
    assert m.n_matched == 4 and m.text == pytest.approx(1.0)
    assert m.block_match == pytest.approx(1.0) and m.position == pytest.approx(1.0)
    assert details["merges"][0]["text"] == "Foco Total" and details["merges"][0]["side"] == "gen"
    # sem a fusão o pareamento é pior (era o que penalizaria a diferença de granularidade)
    plain = match_blocks(
        [Block("Foco Total", 600, 200, 840, 244)], [Block("Foco", 600, 200, 680, 244), Block("Total", 690, 200, 840, 244)]
    )
    assert len(plain) == 1 and plain[0][2] < 0.7


def test_split_reference_block_is_merged_on_the_reference_side():
    split_ref = [SPEC[0], ("Foco", 600, 200, 80, 44, (215, 71, 71)), ("Total", 690, 200, 150, 44, (215, 71, 71)), *SPEC[2:]]
    m, details = run(ref_spec=split_ref)
    assert m.n_merged_ref == 1 and m.n_merged_gen == 0 and m.text == pytest.approx(1.0)
    assert details["merges"][0]["side"] == "ref"


def test_stacked_lines_are_merged_in_reading_order():
    ref = [("Texto em duas linhas", 100, 100, 200, 60, (0, 0, 0))]
    gen = [("duas linhas", 100, 132, 200, 28, (0, 0, 0)), ("Texto em", 100, 100, 200, 30, (0, 0, 0))]  # fora de ordem
    m, details = compute_design2code(refs(ref), doms(gen), VIEWPORT)
    assert m.n_merged_gen == 1 and m.text == pytest.approx(1.0)
    assert details["merges"][0]["text"] == "Texto em duas linhas"


def test_merging_never_hurts_perfect_matches():
    result = match_with_merges(
        [Block("A", 0, 0, 10, 10), Block("B", 12, 0, 22, 10)], [Block("A", 0, 0, 10, 10), Block("B", 12, 0, 22, 10)]
    )
    assert result.n_merged_ref == result.n_merged_gen == 0 and len(result.pairs) == 2


def test_unrelated_far_blocks_are_not_merged():
    ref = [Block("Foco Total", 0, 0, 100, 20)]
    gen = [Block("Foco", 0, 0, 40, 20), Block("Total", 900, 700, 960, 720)]  # longe: não é vizinho
    result = match_with_merges(ref, gen)
    assert result.n_merged_gen == 0 and len(result.pairs) == 1


def test_merge_two_semantics():
    a, b = Block("Total", 90, 0, 150, 20, (1, 1, 1)), Block("Foco", 0, 0, 80, 20, (2, 2, 2))
    merged = merge_two(a, b)
    assert merged.text == "Foco Total" and merged.parts == 2
    assert (merged.x0, merged.y0, merged.x1, merged.y1) == (0, 0, 150, 20)
    assert merged.color == (2, 2, 2)  # cor do bloco maior (a: 60x20; b: 80x20)
    assert merge_two(Block("x", 0, 0, 10, 10, (9, 9, 9)), Block("y", 0, 20, 30, 30, (7, 7, 7))).color == (7, 7, 7)


# ---------------------------------------------------------------- casos de borda


def test_no_pairs_means_zero_scores():
    m, _ = run(ref_spec=[SPEC[0]], gen_spec=[("zzzz", 80, 20, 140, 30, (0, 0, 0))])
    assert m.n_matched == 0
    assert m.block_match == m.text == m.position == m.color == 0.0


def test_empty_generated_page_scores_zero_not_none():
    m, _ = compute_design2code(refs(), [], VIEWPORT)
    assert m.n_gen_blocks == 0 and m.block_match == 0.0 and m.text == 0.0


def test_no_reference_blocks_is_not_computable():
    m, details = compute_design2code([], doms(), VIEWPORT)
    assert m.n_ref_blocks == 0 and m.n_gen_blocks == 4
    assert m.block_match is None and m.text is None and m.position is None and m.color is None
    assert details["pairs"] == []


def test_color_is_none_when_no_pair_has_colors():
    spec = [(t, x, y, w, h, None) for t, x, y, w, h, _ in SPEC]
    ref = [RefBlock(text=t, x0=x, y0=y, x1=x + w, y1=y + h) for t, x, y, w, h, _ in spec]
    gen = [{"text": t, "x": x, "y": y, "w": w, "h": h, "color": None} for t, x, y, w, h, _ in spec]
    m, _ = compute_design2code(ref, gen, VIEWPORT)
    assert m.color is None and m.text == pytest.approx(1.0)


def test_empty_text_blocks_are_ignored():
    m, _ = run(gen_spec=[*SPEC, ("   ", 0, 0, 10, 10, (0, 0, 0))])
    assert m.n_gen_blocks == 4


def test_reference_source_is_recorded():
    m, _ = compute_design2code(refs(), doms(), VIEWPORT, reference_source="ocr")
    assert m.reference_source == "ocr"


# ---------------------------------------------------------------- funções auxiliares


def test_text_similarity():
    assert text_similarity("abc", "abc") == 1.0
    assert text_similarity("", "") == 0.0
    assert text_similarity("abc", "xyz") == 0.0
    assert text_similarity("Foco", "Foco Total") == pytest.approx(2 * 4 / 14)  # Sørensen-Dice = 2M/T


def test_color_similarity():
    assert color_similarity((10, 20, 30), (10, 20, 30)) == 1.0
    assert color_similarity((0, 0, 0), (255, 255, 255)) == pytest.approx(0.0, abs=0.01)
    assert 0.9 < color_similarity((255, 0, 0), (250, 0, 0)) < 1.0


def test_inpaint_text_erases_the_text_pixels():
    image = np.full((100, 200, 3), 255, dtype="uint8")
    image[40:50, 30:80] = 0  # "texto" preto
    cleaned = inpaint_text(image, [[30, 40, 80, 50]])
    assert cleaned.shape == image.shape
    assert cleaned[40:50, 30:80].min() >= 250  # apagado, preenchido com o fundo
    assert (cleaned[:30] == 255).all()  # fora da máscara nada muda
    untouched = inpaint_text(image, [])
    assert (untouched == image).all()
