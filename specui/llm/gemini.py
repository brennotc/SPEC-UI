"""Cliente Gemini (google-genai), portado de src/runner.py.

Mantido do código antigo: pausa fixa entre chamadas, espera exponencial em 429, rotação de
chaves, DailyQuotaExceededError. Removido: fallback para outro modelo e mock silencioso.
"""

import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from specui.llm.base import (
    ConfigurationError,
    DailyQuotaExceededError,
    KeyRing,
    LLMError,
    LLMResponse,
    RateLimiter,
)
from specui.models import Generator, PromptPackage

logger = logging.getLogger(__name__)

# RECITATION: o provedor bloqueia a resposta por reproduzir texto protegido; vem com texto vazio e não é "o modelo respondeu mal"
_REFUSAL_FINISH_REASONS = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "IMAGE_SAFETY", "RECITATION"}
_TRANSIENT_MARKERS = ("500", "502", "503", "504", "unavailable", "overloaded", "deadline", "timed out")


def is_daily_quota_error(exc: Exception) -> bool:
    """Cota DIÁRIA (ex.: quotaId GenerateRequestsPerDayPerProjectPerModel-FreeTier). "free tier" sozinho não basta:
    o limite POR MINUTO do plano gratuito também cita free tier e só pede espera."""
    msg = str(exc).lower()
    return any(kw in msg for kw in ("per day", "perday", "daily"))


def is_rate_limit_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(kw in msg for kw in ("429", "quota", "resource_exhausted", "rate limit"))


def is_model_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(kw in msg for kw in ("not found", "invalid model", "does not exist", "404"))


def is_auth_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(kw in msg for kw in ("api key not valid", "permission_denied", "401", "403", "unauthenticated"))


def is_transient_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(kw in msg for kw in _TRANSIENT_MARKERS)


def _mime_type(path: Path) -> str:
    return {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(
        path.suffix.lower(), "image/png"
    )


class GeminiClient:
    def __init__(
        self,
        generator: Generator,
        keys: list[str],
        client_factory: Callable[[str], Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if generator.provider != "google":
            raise ConfigurationError(f"GeminiClient exige provider 'google', recebeu {generator.provider}")
        self.generator = generator
        self.keys = KeyRing(keys)
        self.limiter = RateLimiter(generator.request_delay_s, generator.max_retries)
        self._factory = client_factory or self._default_factory
        self._sleep = sleep
        self._clients: dict[str, Any] = {}

    def _client(self) -> Any:
        """Um cliente por chave, mantido vivo: o google-genai fecha a conexão quando o objeto é coletado."""
        key = self.keys.current
        if key not in self._clients:
            self._clients[key] = self._factory(key)
        return self._clients[key]

    @staticmethod
    def _default_factory(api_key: str) -> Any:
        from google import genai

        return genai.Client(api_key=api_key)

    # ------------------------------------------------------------------ geração

    def _config(self, system: str, seed: int | None) -> Any:
        from google.genai import types

        gen = self.generator
        kwargs: dict[str, Any] = {
            "system_instruction": system,
            "max_output_tokens": gen.max_output_tokens,
            "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True),
        }
        if seed is not None:
            kwargs["seed"] = seed
        if gen.temperature is not None:  # None = padrão do provedor: não enviar
            kwargs["temperature"] = gen.temperature
        budget = gen.thinking.get("thinking_budget")
        if budget is not None:
            kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=int(budget))
        return types.GenerateContentConfig(**kwargs)

    def _contents(self, pkg: PromptPackage) -> Any:
        from google.genai import types

        if pkg.image_path:
            path = Path(pkg.image_path)
            if not path.is_file():
                raise FileNotFoundError(f"imagem não encontrada: {path}")
            return [
                types.Part.from_bytes(data=path.read_bytes(), mime_type=_mime_type(path)),
                types.Part.from_text(text=pkg.user_text),
            ]
        return pkg.user_text

    def generate(self, pkg: PromptPackage, seed: int | None) -> LLMResponse:
        contents, config = self._contents(pkg), self._config(pkg.system, seed)
        last_exc: Exception | None = None
        attempt = 0
        while attempt < self.limiter.max_retries:
            try:
                self.limiter.wait()
                client = self._client()
                started = time.monotonic()
                response = client.models.generate_content(
                    model=self.generator.model_id, contents=contents, config=config
                )
                latency_ms = int((time.monotonic() - started) * 1000)
                return self._to_response(response, latency_ms)
            except Exception as exc:
                last_exc = exc
                if is_daily_quota_error(exc):
                    exhausted = self.keys.position
                    if self.keys.exhaust_current():  # troca de chave não gasta tentativa
                        logger.warning("Gemini: cota diária esgotada na chave %d; seguindo com a chave %d (%d restante(s))",
                                       exhausted, self.keys.position, self.keys.remaining)
                        continue
                    raise DailyQuotaExceededError(
                        f"Cota diária do Gemini esgotada em todas as {len(self.keys)} chave(s). Rode de novo amanhã.",
                        provider="google",
                    ) from exc
                if is_model_error(exc):
                    raise ConfigurationError(
                        f"modelo '{self.generator.model_id}' indisponível: {exc}"
                    ) from exc
                if is_auth_error(exc) and not is_rate_limit_error(exc):
                    raise ConfigurationError(f"credencial do Gemini recusada: {exc}") from exc
                if is_rate_limit_error(exc):
                    self.keys.rotate()
                    logger.warning("Gemini 429; rotacionando chave e esperando (tentativa %d)", attempt + 1)
                    self._sleep(self.limiter.backoff_seconds(attempt))
                    attempt += 1
                    continue
                if is_transient_error(exc):
                    self._sleep(self.limiter.backoff_seconds(attempt))
                    attempt += 1
                    continue
                raise LLMError(f"falha na chamada ao Gemini: {exc}") from exc
        raise LLMError(f"Gemini: {self.limiter.max_retries} tentativas esgotadas: {last_exc}")

    @staticmethod
    def _to_response(response: Any, latency_ms: int) -> LLMResponse:
        candidate = (getattr(response, "candidates", None) or [None])[0]
        raw_reason = getattr(candidate, "finish_reason", None)
        finish = getattr(raw_reason, "name", None) or (str(raw_reason) if raw_reason is not None else None)
        feedback = getattr(response, "prompt_feedback", None)
        block_reason = getattr(feedback, "block_reason", None)
        refused = bool(block_reason) or finish in _REFUSAL_FINISH_REASONS
        usage = getattr(response, "usage_metadata", None)
        try:
            text = response.text or ""
        except (ValueError, AttributeError):  # resposta bloqueada: .text levanta
            text = ""
        return LLMResponse(
            text=text,
            model_returned=getattr(response, "model_version", None),
            input_tokens=getattr(usage, "prompt_token_count", None),
            output_tokens=getattr(usage, "candidates_token_count", None),
            thoughts_tokens=getattr(usage, "thoughts_token_count", None),
            latency_ms=latency_ms,
            finish_reason=finish,
            truncated=finish == "MAX_TOKENS",
            refused=refused,
            refusal_detail=str(block_reason) if block_reason else (finish if refused else None),
        )

    # ------------------------------------------------------------------ utilitários

    def count_tokens(self, system: str, user_text: str) -> int | None:
        try:
            self.limiter.wait()  # chamada extra à API por célula: passa pelo mesmo limitador da geração
            client = self._client()
            result = client.models.count_tokens(
                model=self.generator.model_id, contents=f"{system}\n\n{user_text}"
            )
            return int(result.total_tokens)
        except Exception:
            logger.warning("count_tokens do Gemini falhou", exc_info=True)
            return None

    def check_model(self) -> str:
        try:
            info = self._client().models.get(model=self.generator.model_id)
        except Exception as exc:
            raise ConfigurationError(
                f"modelo '{self.generator.model_id}' não encontrado no Gemini: {exc}"
            ) from exc
        return str(info.name).removeprefix("models/")
