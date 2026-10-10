"""Blocos de texto de REFERÊNCIA: o design do Figma é o gabarito das métricas visuais.

Fonte preferida: a resposta da API do Figma (references/figma/nodes.raw.json, buscada UMA vez
por scripts/fetch_figma.py; o pipeline NUNCA chama a API). Os nós TEXT viram `RefBlock` em px do
PNG, normalizados pela caixa do frame (assim batem com o screenshot, que tem o tamanho do frame).
Fallback: OCR (EasyOCR, pt) sobre o PNG, para quando o JSON do Figma não está disponível.
"""

import json
import unicodedata
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel

from specui.models import Task

SCALE_TOLERANCE = 0.005


class ReferenceUnavailableError(RuntimeError):
    """Não há como obter os blocos de referência de uma tarefa."""


class RefBlock(BaseModel):
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    color_rgb: tuple[int, int, int] | None = None
    font_size: float | None = None
    source: Literal["figma", "ocr"] = "figma"
    confidence: float = 1.0

    @property
    def area(self) -> float:
        return max(0.0, self.x1 - self.x0) * max(0.0, self.y1 - self.y0)


def normalize_text(text: str) -> str:
    """NFKC, espaços colapsados, sem espaços nas pontas (usado para comparar textos)."""
    return " ".join(unicodedata.normalize("NFKC", text).split())


# ----------------------------------------------------------------------------- Figma


def _text_nodes(node: dict[str, Any], out: list[dict[str, Any]]) -> None:
    """Nós TEXT visíveis (uma camada oculta oculta toda a subárvore)."""
    if node.get("visible") is False or node.get("opacity") == 0:
        return
    if node.get("type") == "TEXT":
        out.append(node)
        return
    for child in node.get("children", []):
        _text_nodes(child, out)


def _solid_rgb(node: dict[str, Any]) -> tuple[int, int, int] | None:
    for fill in node.get("fills", []):
        if fill.get("visible", True) is False:
            continue
        if fill.get("type") != "SOLID":
            return None  # gradiente/imagem: sem cor única
        c = fill["color"]
        return (round(c["r"] * 255), round(c["g"] * 255), round(c["b"] * 255))
    return None


def derive_blocks(
    nodes_response: dict[str, Any], node_id: str, png_size: tuple[int, int]
) -> tuple[list[RefBlock], dict[str, float]]:
    """Blocos de texto do frame `node_id` em px do PNG. Falha se o PNG não estiver em 1x.

    Devolve (blocos, caixa do frame no Figma).
    """
    try:
        document = nodes_response["nodes"][node_id]["document"]
    except (KeyError, TypeError) as exc:
        raise ReferenceUnavailableError(f"nó '{node_id}' ausente na resposta do Figma") from exc
    frame = document.get("absoluteBoundingBox")
    if not frame:
        raise ReferenceUnavailableError(f"nó '{node_id}' sem absoluteBoundingBox (não é um frame?)")

    png_w, png_h = png_size
    scale = png_w / frame["width"]
    if abs(scale - 1) > SCALE_TOLERANCE or png_h != round(frame["height"] * scale):
        raise ReferenceUnavailableError(
            f"PNG {png_w}x{png_h} não bate com o frame {frame['width']}x{frame['height']}: "
            "reexporte o PNG do Figma em escala 1x"
        )

    nodes: list[dict[str, Any]] = []
    _text_nodes(document, nodes)
    blocks: list[RefBlock] = []
    for node in nodes:
        text = normalize_text(node.get("characters", ""))
        box = node.get("absoluteBoundingBox")
        if not text or not box:
            continue
        x0 = (box["x"] - frame["x"]) * scale
        y0 = (box["y"] - frame["y"]) * scale
        x1, y1 = x0 + box["width"] * scale, y0 + box["height"] * scale
        if x1 <= 0 or y1 <= 0 or x0 >= png_w or y0 >= png_h:  # fora do frame (conteúdo cortado)
            continue
        blocks.append(
            RefBlock(
                text=text,
                x0=round(max(0.0, x0), 2), y0=round(max(0.0, y0), 2),
                x1=round(min(float(png_w), x1), 2), y1=round(min(float(png_h), y1), 2),
                color_rgb=_solid_rgb(node),
                font_size=(node.get("style") or {}).get("fontSize"),
            )
        )
    blocks.sort(key=lambda b: (b.y0, b.x0))
    return blocks, frame


def derive_all(
    frames_yaml: str | Path, nodes_raw: str | Path, out_blocks: str | Path, tasks_dir: str | Path
) -> dict[str, Any]:
    """Deriva references/figma/blocks.json de nodes.raw.json (offline; pode rodar à vontade)."""
    from specui.tasks import png_size

    frames = (yaml.safe_load(Path(frames_yaml).read_text(encoding="utf-8")) or {}).get("frames", {})
    response = json.loads(Path(nodes_raw).read_text(encoding="utf-8"))
    result: dict[str, Any] = {}
    for task_id, spec in frames.items():
        node_id = spec.get("node_id")
        if node_id in (None, "", "TODO"):
            continue
        blocks, frame = derive_blocks(response, node_id, png_size(Path(tasks_dir) / spec["png"]))
        result[task_id] = {
            "node_id": node_id,
            "frame": {"width": frame["width"], "height": frame["height"]},
            "blocks": [b.model_dump(mode="json") for b in blocks],
        }
    Path(out_blocks).write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n"
    )
    return result


# ----------------------------------------------------------------------------- OCR (fallback)


def ocr_blocks(png_path: str | Path) -> list[RefBlock]:
    """Blocos por OCR (EasyOCR, pt). Aproximado: cor = tom dominante do texto; sem tamanho de fonte."""
    try:
        import easyocr
        import numpy as np
        from PIL import Image
    except ImportError as exc:
        raise ReferenceUnavailableError(
            "OCR indisponível: instale requirements-ocr.txt (easyocr) ou gere references/figma/blocks.json"
        ) from exc

    reader = easyocr.Reader(["pt"], gpu=False, verbose=False)
    image = np.asarray(Image.open(png_path).convert("RGB"))
    blocks: list[RefBlock] = []
    for quad, text, confidence in reader.readtext(str(png_path)):
        text = normalize_text(text)
        if not text:
            continue
        xs, ys = [p[0] for p in quad], [p[1] for p in quad]
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        region = image[max(0, int(y0)):int(y1) + 1, max(0, int(x0)):int(x1) + 1].reshape(-1, 3)
        color = None
        if len(region):
            background = np.median(region, axis=0)
            far = region[np.abs(region.astype(int) - background).sum(axis=1) > 120]
            if len(far):
                color = tuple(int(v) for v in np.median(far, axis=0))
        blocks.append(
            RefBlock(text=text, x0=float(x0), y0=float(y0), x1=float(x1), y1=float(y1),
                     color_rgb=color, source="ocr", confidence=float(confidence))  # type: ignore[arg-type]
        )
    blocks.sort(key=lambda b: (b.y0, b.x0))
    return blocks


# ----------------------------------------------------------------------------- entrada única


def load_reference_blocks(
    task: Task, references_dir: str | Path, allow_ocr: bool = False
) -> tuple[list[RefBlock], Literal["figma", "ocr"]]:
    """Blocos da tarefa: blocks.json, senão derivados de nodes.raw.json, senão OCR (se permitido)."""
    references_dir = Path(references_dir)
    blocks_json = references_dir / "blocks.json"
    if blocks_json.is_file():
        entry = json.loads(blocks_json.read_text(encoding="utf-8")).get(task.id)
        if entry:
            return [RefBlock.model_validate(b) for b in entry["blocks"]], "figma"
    nodes_raw = references_dir / "nodes.raw.json"
    if nodes_raw.is_file() and task.figma_node_id:
        response = json.loads(nodes_raw.read_text(encoding="utf-8"))
        blocks, _ = derive_blocks(response, task.figma_node_id, task.image_size)
        return blocks, "figma"
    if allow_ocr:
        return ocr_blocks(task.image_path), "ocr"
    raise ReferenceUnavailableError(
        f"sem referência do Figma para '{task.id}': rode scripts/fetch_figma.py (uma vez) ou "
        "ative enable_ocr_fallback"
    )
