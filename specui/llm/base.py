"""Protocolo comum dos clientes de LLM, exceções e chaves de API.

Regras do experimento: modelo FIXO (sem fallback de modelo nem de provedor) e nenhum mock
silencioso. Falhas de infraestrutura viram exceções tipadas que o pipeline traduz em status.
"""

import os
import re
import time
from typing import Protocol

from pydantic import BaseModel

from specui.models import PromptPackage


class LLMError(RuntimeError):
    """Falha da API que não é de configuração nem de cota (vira status `api_error`)."""


class ConfigurationError(RuntimeError):
    """Configuração inválida: modelo inexistente, chave ausente, alias, credencial recusada."""


class QuotaExceededError(RuntimeError):
    """Cota esgotada: o pipeline pausa as células DESTE provedor e segue com os outros."""

    def __init__(self, message: str, provider: str = "") -> None:
        super().__init__(message)
        self.provider = provider


class DailyQuotaExceededError(QuotaExceededError):
    """Cota diária do Gemini esgotada (não adianta tentar de novo hoje)."""


class ProviderQuotaExceededError(QuotaExceededError):
    """Crédito/limite persistente esgotado em um provedor (não adianta repetir a chamada)."""


class ModelMismatchError(RuntimeError):
    """O modelo devolvido difere do solicitado de novo, na mesma célula: interrompe o run."""


class LLMResponse(BaseModel):
    text: str = ""
    model_returned: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    thoughts_tokens: int | None = None
    latency_ms: int = 0
    finish_reason: str | None = None
    truncated: bool = False  # parou por limite de tokens (vira status `truncated`)
    refused: bool = False  # recusa de segurança (vira status `refusal`)
    refusal_detail: str | None = None


class LLMClient(Protocol):
    """Um cliente por gerador (provedor + modelo fixo)."""

    def generate(self, pkg: PromptPackage, seed: int | None) -> LLMResponse: ...

    def count_tokens(self, system: str, user_text: str) -> int | None: ...

    def check_model(self) -> str:
        """Id/versão que a API reporta para o modelo configurado; falha se não existir."""
        ...


# ----------------------------------------------------------------------------- chaves e ritmo


def collect_keys(base_name: str, extra_names: tuple[str, ...] = ()) -> list[str]:
    """Lê BASE, BASE_1 ... BASE_9 (e nomes extras) do ambiente, sem repetir valores."""
    names = [base_name, *(f"{base_name}_{i}" for i in range(1, 10)), *extra_names]
    keys: list[str] = []
    for name in names:
        value = (os.getenv(name) or "").strip()
        if value and value not in keys:
            keys.append(value)
    return keys


class KeyRing:
    """Anel de chaves de um provedor.

    `rotate()` passa à próxima chave ainda utilizável (limite por minuto). `exhaust_current()` marca a chave atual
    como sem cota diária e passa à próxima; devolve False quando TODAS esgotaram (só então o provedor pausa).
    """

    def __init__(self, keys: list[str]) -> None:
        if not keys:
            raise ConfigurationError("nenhuma chave de API configurada para o provedor")
        self._keys = list(keys)
        self._i = 0
        self._exhausted: set[int] = set()

    @property
    def current(self) -> str:
        return self._keys[self._i]

    def rotate(self) -> str:
        for step in range(1, len(self._keys) + 1):
            candidate = (self._i + step) % len(self._keys)
            if candidate not in self._exhausted:
                self._i = candidate
                break
        return self.current

    def exhaust_current(self) -> bool:
        """A chave atual esgotou a cota diária. True se ainda resta outra chave (já selecionada)."""
        self._exhausted.add(self._i)
        if len(self._exhausted) >= len(self._keys):
            return False
        self.rotate()
        return True

    @property
    def position(self) -> int:
        """Índice (1-based) da chave atual, para log; nunca a chave em si."""
        return self._i + 1

    @property
    def remaining(self) -> int:
        return len(self._keys) - len(self._exhausted)

    def __len__(self) -> int:
        return len(self._keys)


class RateLimiter:
    """Pausa fixa entre chamadas + espera exponencial em 429. Um por provedor."""

    def __init__(self, request_delay_s: float = 3.0, max_retries: int = 5) -> None:
        self.request_delay_s = max(0.0, request_delay_s)
        self.max_retries = max(1, max_retries)

    def wait(self) -> None:
        if self.request_delay_s > 0:
            time.sleep(self.request_delay_s)

    def backoff_seconds(self, attempt: int) -> float:
        """`request_delay_s * 2**attempt` (attempt começa em 0), limitado a 5 minutos."""
        return min(300.0, max(0.5, self.request_delay_s) * (2**attempt))

    def backoff_wait(self, attempt: int) -> None:
        time.sleep(self.backoff_seconds(attempt))


# ----------------------------------------------------------------------------- verificação do modelo

_VERSION_SUFFIX = re.compile(r"^(?:-\d+)+$")


def model_matches(requested: str, returned: str | None) -> bool:
    """Igualdade, ou prefixo seguido só de sufixo numérico de versão (ex.: ...-flash-001)."""
    if not returned:
        return False
    requested = requested.removeprefix("models/")
    returned = returned.removeprefix("models/")
    if returned == requested:
        return True
    return returned.startswith(requested) and bool(_VERSION_SUFFIX.match(returned[len(requested):]))
