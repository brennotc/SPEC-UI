"""Clientes de LLM: um por gerador (provedor + modelo fixo). Nunca há fallback entre eles."""

from specui.llm.base import (
    ConfigurationError,
    DailyQuotaExceededError,
    LLMClient,
    LLMError,
    LLMResponse,
    ModelMismatchError,
    QuotaExceededError,
    collect_keys,
    model_matches,
)
from specui.llm.gemini import GeminiClient
from specui.llm.mock import MockClient
from specui.models import Generator

__all__ = [
    "ConfigurationError",
    "DailyQuotaExceededError",
    "GeminiClient",
    "LLMClient",
    "LLMError",
    "LLMResponse",
    "MockClient",
    "ModelMismatchError",
    "QuotaExceededError",
    "make_client",
    "model_matches",
]


def make_client(generator: Generator) -> LLMClient:
    """Cria o cliente do gerador. Chave ausente é erro de configuração (nunca vira mock)."""
    if generator.provider == "mock":
        return MockClient(generator)
    if generator.provider == "google":
        keys = collect_keys("GEMINI_API_KEY", ("GOOGLE_API_KEY",))
        if not keys:
            raise ConfigurationError("defina GEMINI_API_KEY (ou GEMINI_API_KEY_1..9) no .env")
        return GeminiClient(generator, keys)
    raise ConfigurationError(f"provedor desconhecido: {generator.provider}")
