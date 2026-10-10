"""Análise estatística: contraste principal (ITT), condicional, consistência entre modelos, itens e prompts livres."""

from specui.analysis.contrasts import (
    EffectResult,
    consistency,
    main_contrast,
    ols_robustness,
    stratum_table,
)
from specui.analysis.data import AnalysisRefused, prepare_frame

__all__ = [
    "AnalysisRefused", "EffectResult", "consistency", "main_contrast", "ols_robustness",
    "prepare_frame", "stratum_table",
]
