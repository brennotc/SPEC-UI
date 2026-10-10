"""Métricas de pixel entre o render e o design: MAE (Figma2Code) e SSIM (secundária)."""

from pathlib import Path

import numpy as np
from PIL import Image


def load_rgb(source: str | Path | Image.Image, size: tuple[int, int] | None = None) -> np.ndarray:
    """Imagem como float32 em [0, 1], RGB. Transparência é composta sobre branco; `size`
    (largura, altura) reamostra quando as dimensões diferem."""
    image = Image.open(source) if not isinstance(source, Image.Image) else source
    if image.mode in ("RGBA", "LA", "P"):
        rgba = image.convert("RGBA")
        base = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        image = Image.alpha_composite(base, rgba)
    image = image.convert("RGB")
    if size is not None and image.size != size:
        image = image.resize(size, Image.Resampling.LANCZOS)
    return np.asarray(image, dtype=np.float32) / 255.0


def mae(render: str | Path, design: str | Path) -> float:
    """Erro absoluto médio normalizado (0 = idêntico, 1 = máximo), como no Figma2Code.
    O render é reamostrado ao tamanho do design se as dimensões diferirem."""
    ref = load_rgb(design)
    gen = load_rgb(render, size=(ref.shape[1], ref.shape[0]))
    return float(np.abs(ref - gen).mean())


def ssim(render: str | Path, design: str | Path) -> float:
    """SSIM (secundária: Figma e navegador desenham fontes de modos diferentes, então
    nunca chega perto de 1 mesmo numa cópia fiel)."""
    from skimage.metrics import structural_similarity

    ref = load_rgb(design)
    gen = load_rgb(render, size=(ref.shape[1], ref.shape[0]))
    return float(structural_similarity(ref, gen, channel_axis=2, data_range=1.0))
