"""Métricas visuais por bloco de texto (Design2Code, NAACL 2025).

Compara os blocos de texto da página gerada (lidos do DOM) com os do design do Figma:

- Block-Match: área dos blocos pareados / área de todos os blocos (dos dois lados);
- Text:        similaridade de caracteres (Sørensen-Dice = 2M/T) dos pares;
- Position:    1 - max(|Δx|, |Δy|) entre os centros normalizados;
- Color:       diferença CIEDE2000 das cores de texto, normalizada para [0, 1];
- CLIP:        similaridade CLIP dos screenshots com o texto removido por inpainting.

Pareamento: algoritmo húngaro (Jonker-Volgenant, scipy) sobre a similaridade de texto, descartando
pares com similaridade < 0,5. Como o DOM e o Figma dividem o texto em granularidades diferentes,
há uma busca de FUSÃO de blocos vizinhos (apêndice C do paper): funde-se um par de blocos
adjacentes, do mesmo lado, quando isso aumenta a similaridade total do pareamento.
"""

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import linear_sum_assignment

from specui.metrics.reference import RefBlock, normalize_text
from specui.models import Design2CodeMetrics

MIN_SIMILARITY = 0.5  # pares abaixo disso não contam (como no Design2Code)
MAX_PARTS = 6  # um bloco fundido junta no máximo 6 blocos originais
MAX_MERGE_ITERATIONS = 80
_EPS = 1e-9


@dataclass(frozen=True)
class Block:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    color: tuple[int, int, int] | None = None
    parts: int = 1  # quantos blocos originais foram fundidos neste

    @property
    def w(self) -> float:
        return max(0.0, self.x1 - self.x0)

    @property
    def h(self) -> float:
        return max(0.0, self.y1 - self.y0)

    @property
    def area(self) -> float:
        return self.w * self.h

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    def box(self) -> list[float]:
        return [round(self.x0, 2), round(self.y0, 2), round(self.x1, 2), round(self.y1, 2)]


def blocks_from_ref(refs: Sequence[RefBlock]) -> list[Block]:
    return [Block(normalize_text(r.text), r.x0, r.y0, r.x1, r.y1, r.color_rgb) for r in refs if r.text.strip()]


def blocks_from_dom(dom_blocks: Sequence[dict[str, Any]]) -> list[Block]:
    """Blocos do `dom_blocks.js`: {text, x, y, w, h, color, ...} em px do viewport."""
    out: list[Block] = []
    for b in dom_blocks:
        text = normalize_text(b.get("text", ""))
        if not text:
            continue
        color = tuple(b["color"]) if b.get("color") else None
        out.append(Block(text, b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"], color))  # type: ignore[arg-type]
    return out


@lru_cache(maxsize=200_000)
def text_similarity(a: str, b: str) -> float:
    """Sørensen-Dice em nível de caractere (= SequenceMatcher.ratio = 2M/T); 0 se ambos vazios."""
    if not a and not b:
        return 0.0
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


# ----------------------------------------------------------------------------- pareamento


def match_blocks(ref: Sequence[Block], gen: Sequence[Block], min_sim: float = MIN_SIMILARITY) -> list[tuple[int, int, float]]:
    """Pareamento ótimo 1:1 (húngaro) pela similaridade de texto; descarta pares < min_sim."""
    if not ref or not gen:
        return []
    sim = np.array([[text_similarity(r.text, g.text) for g in gen] for r in ref])
    rows, cols = linear_sum_assignment(-sim)
    return [(int(i), int(j), float(sim[i, j])) for i, j in zip(rows, cols, strict=True) if sim[i, j] >= min_sim]


def _score(pairs: Sequence[tuple[int, int, float]]) -> float:
    return sum(s for _, _, s in pairs)


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _adjacent(a: Block, b: Block) -> bool:
    """Vizinhos que podem ser pedaços do mesmo texto: na mesma linha (lado a lado) ou em linhas
    consecutivas (empilhados), com folga de até ~1 altura de linha."""
    line = max(a.h, b.h, 1.0)
    v_overlap = _overlap(a.y0, a.y1, b.y0, b.y1)
    if v_overlap >= 0.5 * min(a.h, b.h):  # mesma linha
        gap_x = max(a.x0, b.x0) - min(a.x1, b.x1)
        if gap_x <= line:
            return True
    h_overlap = _overlap(a.x0, a.x1, b.x0, b.x1)
    if h_overlap >= 0.3 * min(a.w, b.w):  # linhas empilhadas
        gap_y = max(a.y0, b.y0) - min(a.y1, b.y1)
        if gap_y <= 1.5 * line:
            return True
    return False


def merge_two(a: Block, b: Block) -> Block:
    """Funde dois blocos: caixa união, texto em ordem de leitura, cor do bloco maior."""
    first, second = (a, b) if (a.y0, a.x0) <= (b.y0, b.x0) else (b, a)
    if _overlap(a.y0, a.y1, b.y0, b.y1) >= 0.5 * min(a.h, b.h):  # mesma linha: esquerda -> direita
        first, second = (a, b) if a.x0 <= b.x0 else (b, a)
    return Block(
        text=f"{first.text} {second.text}".strip(),
        x0=min(a.x0, b.x0), y0=min(a.y0, b.y0), x1=max(a.x1, b.x1), y1=max(a.y1, b.y1),
        color=(a if a.area >= b.area else b).color, parts=a.parts + b.parts,
    )


@dataclass
class MatchResult:
    pairs: list[tuple[int, int, float]]
    ref: list[Block]
    gen: list[Block]
    n_merged_ref: int = 0
    n_merged_gen: int = 0
    merges: list[dict[str, Any]] = field(default_factory=list)


def match_with_merges(
    ref: Sequence[Block], gen: Sequence[Block], min_sim: float = MIN_SIMILARITY,
    max_iterations: int = MAX_MERGE_ITERATIONS,
) -> MatchResult:
    """Pareamento com fusão gulosa de vizinhos: a cada passo aplica a fusão (em qualquer lado)
    que mais aumenta a similaridade total; para quando nenhuma fusão melhora."""
    ref, gen = list(ref), list(gen)
    pairs = match_blocks(ref, gen, min_sim)
    score = _score(pairs)
    merges: list[dict[str, Any]] = []

    for _ in range(max_iterations):
        matched_ref = {i for i, _, s in pairs if s >= 0.999}
        matched_gen = {j for _, j, s in pairs if s >= 0.999}
        best: tuple[float, str, int, int, Block, list[tuple[int, int, float]]] | None = None
        for side, blocks, perfect in (("ref", ref, matched_ref), ("gen", gen, matched_gen)):
            for i in range(len(blocks)):
                for j in range(i + 1, len(blocks)):
                    if (i in perfect and j in perfect) or blocks[i].parts + blocks[j].parts > MAX_PARTS:
                        continue  # fundir dois blocos já perfeitos nunca ajuda
                    if not _adjacent(blocks[i], blocks[j]):
                        continue
                    merged = merge_two(blocks[i], blocks[j])
                    rest = [b for k, b in enumerate(blocks) if k not in (i, j)] + [merged]
                    new_pairs = match_blocks(rest, gen, min_sim) if side == "ref" else match_blocks(ref, rest, min_sim)
                    new_score = _score(new_pairs)
                    if new_score > score + 1e-6 and (best is None or new_score > best[0]):
                        best = (new_score, side, i, j, merged, new_pairs)
        if best is None:
            break
        score, side, i, j, merged, pairs = best
        blocks = ref if side == "ref" else gen
        merges.append({"side": side, "text": merged.text, "box": merged.box(), "parts": merged.parts})
        blocks[:] = [b for k, b in enumerate(blocks) if k not in (i, j)] + [merged]

    return MatchResult(
        pairs=pairs, ref=ref, gen=gen,
        n_merged_ref=sum(1 for b in ref if b.parts > 1), n_merged_gen=sum(1 for b in gen if b.parts > 1),
        merges=merges,
    )


# ----------------------------------------------------------------------------- sub-métricas


def _ciede2000(a: Sequence[tuple[int, int, int]], b: Sequence[tuple[int, int, int]]) -> np.ndarray:
    from skimage.color import deltaE_ciede2000, rgb2lab

    lab_a = rgb2lab(np.array(a, dtype=float).reshape(-1, 1, 3) / 255.0)
    lab_b = rgb2lab(np.array(b, dtype=float).reshape(-1, 1, 3) / 255.0)
    return deltaE_ciede2000(lab_a, lab_b).reshape(-1)


def color_similarity(c1: tuple[int, int, int], c2: tuple[int, int, int]) -> float:
    """max(0, 1 - ΔE2000/100): 1 = cores idênticas."""
    return float(max(0.0, 1.0 - _ciede2000([c1], [c2])[0] / 100.0))


def compute_design2code(
    ref_blocks: Sequence[RefBlock], dom_blocks: Sequence[dict[str, Any]], viewport: tuple[int, int],
    reference_source: str = "figma",
) -> tuple[Design2CodeMetrics, dict[str, Any]]:
    """Block-Match, Text, Position e Color. Devolve (métricas, detalhes para o painel).

    Sem blocos de referência a métrica não é calculável (None). Com blocos mas sem NENHUM par,
    as quatro valem 0 por definição (nenhum bloco casou).
    """
    ref0, gen0 = blocks_from_ref(ref_blocks), blocks_from_dom(dom_blocks)
    metrics = Design2CodeMetrics(
        n_ref_blocks=len(ref0), n_gen_blocks=len(gen0), n_matched=0,
        reference_source=reference_source,  # type: ignore[arg-type]
    )
    details: dict[str, Any] = {"pairs": [], "unmatched_ref": [], "unmatched_gen": [], "merges": []}
    if not ref0:
        return metrics, details

    result = match_with_merges(ref0, gen0)
    ref, gen, pairs = result.ref, result.gen, result.pairs
    width, height = viewport
    page = float(width * height)
    total_area = sum(b.area for b in ref) + sum(b.area for b in gen)
    matched_area = sum(ref[i].area + gen[j].area for i, j, _ in pairs)

    metrics.n_matched = len(pairs)
    metrics.n_merged_ref, metrics.n_merged_gen = result.n_merged_ref, result.n_merged_gen
    metrics.block_match = matched_area / total_area if total_area > 0 else 0.0
    if pairs:
        metrics.text = float(np.mean([s for _, _, s in pairs]))
        metrics.position = float(np.mean([
            max(0.0, 1.0 - max(abs(ref[i].cx - gen[j].cx) / width, abs(ref[i].cy - gen[j].cy) / height))
            for i, j, _ in pairs
        ]))
        with_color = [(i, j) for i, j, _ in pairs if ref[i].color and gen[j].color]
        if with_color:
            delta = _ciede2000([ref[i].color for i, _ in with_color], [gen[j].color for _, j in with_color])  # type: ignore[misc]
            metrics.color = float(np.mean(np.maximum(0.0, 1.0 - delta / 100.0)))
    else:
        metrics.text = metrics.position = metrics.color = 0.0

    matched_ref, matched_gen = {i for i, _, _ in pairs}, {j for _, j, _ in pairs}
    details = {
        "viewport": [width, height],
        "page_area": page,
        "pairs": [
            {"ref": {"text": ref[i].text, "box": ref[i].box(), "parts": ref[i].parts},
             "gen": {"text": gen[j].text, "box": gen[j].box(), "parts": gen[j].parts},
             "similarity": round(s, 4)}
            for i, j, s in pairs
        ],
        "unmatched_ref": [{"text": b.text, "box": b.box()} for k, b in enumerate(ref) if k not in matched_ref],
        "unmatched_gen": [{"text": b.text, "box": b.box()} for k, b in enumerate(gen) if k not in matched_gen],
        "merges": result.merges,
    }
    return metrics, details


def write_pairs(path: str | Path, details: dict[str, Any]) -> str:
    Path(path).write_text(json.dumps(details, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    return str(path)


# ----------------------------------------------------------------------------- CLIP sem texto


def inpaint_text(image_rgb: np.ndarray, boxes: Sequence[Sequence[float]], dilate: int = 3) -> np.ndarray:
    """Apaga os blocos de texto com inpainting (Telea, raio 3), como no Design2Code."""
    import cv2

    h, w = image_rgb.shape[:2]
    mask = np.zeros((h, w), dtype=np.uint8)
    for x0, y0, x1, y1 in boxes:
        xa, ya = max(0, math.floor(x0) - dilate), max(0, math.floor(y0) - dilate)
        xb, yb = min(w, math.ceil(x1) + dilate), min(h, math.ceil(y1) + dilate)
        if xb > xa and yb > ya:
            mask[ya:yb, xa:xb] = 255
    bgr = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR)
    return cv2.cvtColor(cv2.inpaint(bgr, mask, 3, cv2.INPAINT_TELEA), cv2.COLOR_BGR2RGB)


def with_boxes(blocks: Sequence[Block]) -> list[list[float]]:
    return [[b.x0, b.y0, b.x1, b.y1] for b in blocks]


__all__ = [
    "Block", "MatchResult", "blocks_from_dom", "blocks_from_ref", "color_similarity", "compute_design2code",
    "inpaint_text", "match_blocks", "match_with_merges", "merge_two", "text_similarity", "with_boxes", "write_pairs",
]
