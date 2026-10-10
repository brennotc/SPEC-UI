"""Embeddings de imagem como FUNÇÃO FIXA de similaridade (sem instrução, sem rubrica):

- VES (Figma2Code, ICLR 2026): cosseno entre embeddings DINOv2 do render e do design;
- CLIP ViT-B/32 (Design2Code): cosseno entre embeddings CLIP, após remover o texto por inpainting.

torch/transformers só são importados aqui, dentro das funções, e os modelos são carregados uma
vez por processo (cache em disco em `cache_dir`). Sem os pacotes, `embeddings_available()` diz
por quê e as métricas ficam None (o pipeline segue).

As imagens são redimensionadas INTEIRAS para 224x224 (sem corte central): o recorte padrão dos
processadores descartaria as bordas laterais do frame 1440x900.
"""

import os
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

# No Windows sem modo desenvolvedor o cache não usa symlinks (funciona, só ocupa mais disco).
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

DINOV2_MODEL = "facebook/dinov2-base"
CLIP_MODEL = "openai/clip-vit-base-patch32"
_INPUT_SIZE = (224, 224)


def embeddings_available() -> tuple[bool, str | None]:
    """(disponível, motivo se não)."""
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except ImportError as exc:
        return False, f"{exc.name} não instalado (pip install -r requirements-ml.txt)"
    return True, None


def _cache(cache_dir: str | Path | None) -> str | None:
    return str(Path(cache_dir).expanduser()) if cache_dir else None


@lru_cache(maxsize=2)
def _dinov2(cache_dir: str | None):
    from transformers import AutoImageProcessor, AutoModel

    processor = AutoImageProcessor.from_pretrained(DINOV2_MODEL, cache_dir=cache_dir)
    model = AutoModel.from_pretrained(DINOV2_MODEL, cache_dir=cache_dir).eval()
    return processor, model


@lru_cache(maxsize=2)
def _clip(cache_dir: str | None):
    from transformers import CLIPModel, CLIPProcessor

    processor = CLIPProcessor.from_pretrained(CLIP_MODEL, cache_dir=cache_dir)
    model = CLIPModel.from_pretrained(CLIP_MODEL, cache_dir=cache_dir).eval()
    return processor, model


def _as_pil(image: str | Path | Image.Image | np.ndarray) -> Image.Image:
    if isinstance(image, np.ndarray):
        image = Image.fromarray(image.astype("uint8"))
    elif not isinstance(image, Image.Image):
        image = Image.open(image)
    if image.mode in ("RGBA", "LA", "P"):
        rgba = image.convert("RGBA")
        base = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        image = Image.alpha_composite(base, rgba)
    return image.convert("RGB").resize(_INPUT_SIZE, Image.Resampling.BICUBIC)


def _normalize(vector: np.ndarray) -> np.ndarray:
    vector = vector.astype("float64").reshape(-1)
    return vector / np.linalg.norm(vector)


def dinov2_embedding(image, cache_dir: str | Path | None = None) -> np.ndarray:
    """Embedding DINOv2 (token CLS, com a normalização final do modelo), L2-normalizado."""
    import torch

    processor, model = _dinov2(_cache(cache_dir))
    inputs = processor(images=_as_pil(image), return_tensors="pt", do_resize=False, do_center_crop=False)
    with torch.no_grad():
        out = model(**inputs)
    return _normalize(out.pooler_output[0].numpy())


def clip_embedding(image, cache_dir: str | Path | None = None) -> np.ndarray:
    """Embedding de imagem do CLIP ViT-B/32, L2-normalizado."""
    import torch

    processor, model = _clip(_cache(cache_dir))
    inputs = processor(images=_as_pil(image), return_tensors="pt", do_resize=False, do_center_crop=False)
    with torch.no_grad():
        features = model.get_image_features(pixel_values=inputs["pixel_values"])
    features = getattr(features, "pooler_output", features)  # transformers recentes devolvem um objeto
    return _normalize(features[0].numpy())


def ves_dinov2(render, design, cache_dir: str | Path | None = None) -> float:
    """VES = cos(DINOv2(render), DINOv2(design))."""
    return float(np.dot(dinov2_embedding(render, cache_dir), dinov2_embedding(design, cache_dir)))


def clip_cosine(image_a, image_b, cache_dir: str | Path | None = None) -> float:
    return float(np.dot(clip_embedding(image_a, cache_dir), clip_embedding(image_b, cache_dir)))
