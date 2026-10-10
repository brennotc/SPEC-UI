"""Embeddings de imagem como FUNÇÃO FIXA de similaridade (sem instrução, sem rubrica):

- VES (Figma2Code, ICLR 2026): cosseno entre embeddings DINOv2 do render e do design;
- CLIP ViT-B/32 (Design2Code): cosseno entre embeddings CLIP, após remover o texto por inpainting.

torch/transformers só são importados aqui, dentro das funções, e os modelos são carregados uma
vez por processo, SÓ do cache em disco em `cache_dir` (`local_files_only=True` e `HF_HUB_OFFLINE=1`: o experimento nunca acessa
o Hub). Modelo ausente do cache é `ConfigurationError` com o nome e a pasta esperada; `model_snapshot` devolve o sha do
snapshot em uso (vai para o record). Sem os pacotes, `embeddings_available()` diz por quê e as métricas ficam None.

As imagens são redimensionadas INTEIRAS para 224x224 (sem corte central): o recorte padrão dos
processadores descartaria as bordas laterais do frame 1440x900.
"""

import os
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

from specui.llm.base import ConfigurationError

# Nada neste processo toca a rede do Hub (setdefault: quem precisar baixar, de propósito, define HF_HUB_OFFLINE=0 antes de importar).
os.environ.setdefault("HF_HUB_OFFLINE", "1")
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


def _cache_root(cache_dir: str | Path | None) -> Path:
    if cache_dir:
        return Path(cache_dir).expanduser()
    return Path(os.environ.get("HF_HUB_CACHE") or Path.home() / ".cache" / "huggingface" / "hub")


def model_snapshot(model: str, cache_dir: str | Path | None = None) -> str:
    """sha do snapshot de `model` no cache local (o que `from_pretrained(..., local_files_only=True)` carrega).

    Sem o modelo no cache: `ConfigurationError` com o nome e a pasta esperada. O sha vem de `refs/main`; sem ele, do único
    snapshot existente."""
    root = _cache_root(cache_dir)
    folder = root / f"models--{model.replace('/', '--')}"
    hint = (f"modelo '{model}' ausente do cache local ({folder}); o experimento não acessa o Hub. Baixe uma vez, com rede: "
            f"python -c \"import os; os.environ['HF_HUB_OFFLINE']='0'; from huggingface_hub import snapshot_download; "
            f"snapshot_download('{model}', cache_dir=r'{root}')\"")
    snapshots = folder / "snapshots"
    if not snapshots.is_dir():
        raise ConfigurationError(hint)
    ref = folder / "refs" / "main"
    sha = ref.read_text(encoding="utf-8").strip() if ref.is_file() else None
    if sha is None:
        found = [d.name for d in snapshots.iterdir() if d.is_dir()]
        sha = found[0] if len(found) == 1 else None
    if not sha or not (snapshots / sha).is_dir() or not any((snapshots / sha).iterdir()):
        raise ConfigurationError(hint)
    return sha


def ensure_cached(cache_dir: str | Path | None = None) -> dict[str, str]:
    """Os dois modelos no cache (antes de gastar API): {nome: sha}. `ConfigurationError` no primeiro que faltar."""
    return {name: model_snapshot(name, cache_dir) for name in (DINOV2_MODEL, CLIP_MODEL)}


def model_version(model: str, cache_dir: str | Path | None = None) -> str:
    """`<nome>@<sha do snapshot>`, como gravado no record."""
    return f"{model}@{model_snapshot(model, cache_dir)}"


@lru_cache(maxsize=2)
def _dinov2(cache_dir: str | None):
    model_snapshot(DINOV2_MODEL, cache_dir)  # ConfigurationError legível em vez do traceback do Hub
    from transformers import AutoImageProcessor, AutoModel

    processor = AutoImageProcessor.from_pretrained(DINOV2_MODEL, cache_dir=cache_dir, local_files_only=True)
    model = AutoModel.from_pretrained(DINOV2_MODEL, cache_dir=cache_dir, local_files_only=True).eval()
    return processor, model


@lru_cache(maxsize=2)
def _clip(cache_dir: str | None):
    model_snapshot(CLIP_MODEL, cache_dir)  # ConfigurationError legível em vez do traceback do Hub
    from transformers import CLIPModel, CLIPProcessor

    processor = CLIPProcessor.from_pretrained(CLIP_MODEL, cache_dir=cache_dir, local_files_only=True)
    model = CLIPModel.from_pretrained(CLIP_MODEL, cache_dir=cache_dir, local_files_only=True).eval()
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
