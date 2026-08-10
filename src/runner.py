"""LLM Runner — multi-provider HTML generation with Gemini-first support.

Supported providers
-------------------
* ``google``   — Google Gemini via the ``google-genai`` SDK (default)
* ``openai``   — OpenAI GPT models via the ``openai`` SDK
* ``anthropic``— Anthropic Claude models via the ``anthropic`` SDK

Automatic mock fallback
-----------------------
When no API key is found for the configured provider, the runner switches
to deterministic mock mode so the pipeline can be exercised offline.

Gemini rate-limit handling
--------------------------
:class:`GeminiRateLimiter` enforces a configurable inter-request delay and
implements exponential back-off on HTTP 429 errors.  Multiple API keys are
supported via ``GEMINI_API_KEY``, ``GEMINI_API_KEY_1``, ``GEMINI_API_KEY_2``,
…, and the runner cycles through them on 429 responses to spread quota usage.
"""

from __future__ import annotations

import base64
import hashlib
import itertools
import logging
import mimetypes
import os
import random
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from .models import BenchmarkItem, RunConfig

if TYPE_CHECKING:
    pass  # avoid circular import if TYPE_CHECKING block is needed later

logger = logging.getLogger(__name__)

# ── Gemini model names ──────────────────────────────────────────────────────
_GEMINI_DEFAULT_MODEL = "gemini-2.5-flash"
_GEMINI_FALLBACK_MODEL = "gemini-1.5-pro"

# ── System prompt template ──────────────────────────────────────────────────
_SYSTEM_PROMPT_TEMPLATE = (
    "You are an expert front-end developer. "
    "Generate a complete, self-contained HTML page that includes all required "
    "CSS inside a <style> block and all JavaScript inside <script> blocks. "
    "Return ONLY the raw HTML — no markdown fences, no explanations, no "
    "preamble. The output must start with <!DOCTYPE html> and be valid HTML5.\n\n"
    "Task:\n{task}"
)

# ── Markdown fence stripper (handles ```html ... ``` etc.) ──────────────────
_FENCE_RE = re.compile(r"^```[a-zA-Z]*\n?|```\s*$", re.MULTILINE)


def _strip_fences(code: str) -> str:
    """Remove leading/trailing markdown code fences from LLM output."""
    return _FENCE_RE.sub("", code).strip()


# ---------------------------------------------------------------------------
# Gemini rate limiter
# ---------------------------------------------------------------------------


class GeminiRateLimiter:
    """Enforces inter-request delay and exponential back-off for Gemini calls.

    Args:
        request_delay_s: Fixed pause (seconds) applied *before* every call.
            Keeps the average request rate inside Google's free-tier quota.
            Recommended range: 2–4 seconds.
        max_retries: Maximum number of retry attempts after an HTTP 429
            response before giving up and raising :class:`RuntimeError`.
    """

    def __init__(self, request_delay_s: float = 3.0, max_retries: int = 4) -> None:
        self.request_delay_s = max(0.0, request_delay_s)
        self.max_retries = max(1, max_retries)

    def wait(self) -> None:
        """Enforce the fixed inter-request delay."""
        if self.request_delay_s > 0:
            time.sleep(self.request_delay_s)

    def backoff_wait(self, attempt: int) -> None:
        """Sleep for ``request_delay_s * 2^attempt`` seconds (exponential back-off).

        Args:
            attempt: Zero-based attempt index (0 = first retry → shortest wait).
        """
        wait_s = self.request_delay_s * (2 ** attempt)
        logger.warning(
            "Gemini rate limit (429) — backing off %.1f s (attempt %d/%d).",
            wait_s,
            attempt + 1,
            self.max_retries,
        )
        time.sleep(wait_s)

    @staticmethod
    def is_rate_limit_error(exc: Exception) -> bool:
        """Return ``True`` when *exc* looks like a quota / rate-limit error."""
        msg = str(exc).lower()
        return any(kw in msg for kw in ("429", "quota", "resource_exhausted", "rate limit"))

    @staticmethod
    def is_model_error(exc: Exception) -> bool:
        """Return ``True`` when *exc* indicates the model name is invalid/unavailable."""
        msg = str(exc).lower()
        return any(kw in msg for kw in ("not found", "invalid model", "does not exist"))


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------


class LLMRunner:
    """Generates HTML artifacts by calling an LLM API or a mock fallback.

    Args:
        config: :class:`~src.models.RunConfig` instance controlling provider,
            model, delays, and output paths.
    """

    def __init__(self, config: RunConfig) -> None:
        self.config = config
        self._output_dir = Path(config.output_dir)
        self._artifacts_dir = self._output_dir / "artifacts"
        self._artifacts_dir.mkdir(parents=True, exist_ok=True)

        # ── Resolve mock mode ──────────────────────────────────────────
        self._mock_mode = config.mock_mode
        if not self._mock_mode:
            self._mock_mode = self._check_key_and_maybe_mock()

        # ── Gemini-specific setup ──────────────────────────────────────
        self._gemini_keys: list[str] = self._collect_gemini_keys()
        self._key_cycle: itertools.cycle[str] | None = (
            itertools.cycle(self._gemini_keys) if self._gemini_keys else None
        )
        self._rate_limiter = GeminiRateLimiter(
            request_delay_s=config.gemini_request_delay_s,
            max_retries=config.gemini_max_retries,
        )

        mode_label = "MOCK" if self._mock_mode else f"LIVE ({config.provider.upper()})"
        logger.info("LLMRunner initialised — mode: %s", mode_label)
        if not self._mock_mode and config.provider == "google" and self._gemini_keys:
            logger.info(
                "Gemini: %d API key(s) loaded; delay=%.1f s; max_retries=%d; model=%s",
                len(self._gemini_keys),
                config.gemini_request_delay_s,
                config.gemini_max_retries,
                config.model or _GEMINI_DEFAULT_MODEL,
            )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run(
        self, item: BenchmarkItem, prompt_type: Literal["No_Spec", "With_Spec"]
    ) -> tuple[str, Path]:
        """Generate HTML for *item* using *prompt_type*.

        Args:
            item: The benchmark task to generate code for.
            prompt_type: Which prompt variant to use.

        Returns:
            A ``(raw_code, artifact_path)`` tuple where *raw_code* is the
            cleaned HTML string and *artifact_path* points to the saved file.
        """
        task_text = (
            item.prompt_no_spec if prompt_type == "No_Spec" else item.prompt_with_spec
        )
        full_prompt = _SYSTEM_PROMPT_TEMPLATE.format(task=task_text)

        image_path: str | None = (
            item.image_path if item.multimodal and item.image_path else None
        )

        if self._mock_mode:
            raw_code = self._mock_response(item, prompt_type)
        elif self.config.provider == "google":
            raw_code = self._call_google(full_prompt, image_path=image_path)
        elif self.config.provider == "openai":
            raw_code = self._call_openai(full_prompt, image_path=image_path)
        elif self.config.provider == "anthropic":
            raw_code = self._call_anthropic(full_prompt, image_path=image_path)
        else:
            raise ValueError(f"Unknown provider '{self.config.provider}'.")

        raw_code = _strip_fences(raw_code)

        # Guard against empty responses
        if not raw_code.strip():
            logger.warning(
                "LLM returned an empty response for %s [%s]. Using minimal fallback.",
                item.id,
                prompt_type,
            )
            raw_code = (
                "<!DOCTYPE html><html lang='en'><head><meta charset='UTF-8'>"
                "<title>Empty Response</title></head>"
                "<body><p>LLM returned no output.</p></body></html>"
            )

        artifact_path = self._save_artifact(item.id, prompt_type, raw_code)
        logger.debug("Saved artifact → %s", artifact_path)
        return raw_code, artifact_path

    # ------------------------------------------------------------------
    # Provider implementations
    # ------------------------------------------------------------------

    @staticmethod
    def _load_image_bytes(image_path: str) -> tuple[bytes, str]:
        """Read image bytes and detect MIME type from file extension.

        Args:
            image_path: Absolute or relative path to the image file.

        Returns:
            ``(raw_bytes, mime_type)`` tuple, e.g.
            ``(b'...', 'image/png')``.

        Raises:
            FileNotFoundError: When *image_path* does not exist.
            ValueError: When the extension is not a recognised image type.
        """
        path = Path(image_path)
        if not path.is_file():
            raise FileNotFoundError(f"Image not found: '{image_path}'")

        ext = path.suffix.lower()
        _MIME_MAP = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".gif": "image/gif",
        }
        mime_type = _MIME_MAP.get(ext) or mimetypes.guess_type(image_path)[0] or "image/png"
        return path.read_bytes(), mime_type

    def _call_google(self, prompt: str, *, image_path: str | None = None) -> str:
        """Call the Gemini API with key rotation and exponential back-off.

        When *image_path* is provided the request is sent as a multimodal
        prompt (image + text) using ``types.Part.from_bytes``.
        """
        try:
            from google import genai  # type: ignore[import-untyped]
            from google.genai import types  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError(
                "google-genai package not installed. Run: pip install google-genai"
            ) from exc

        if self._key_cycle is None:
            raise RuntimeError(
                "No Gemini API keys available. Set GEMINI_API_KEY in your environment."
            )

        # Build the contents payload — multimodal or text-only
        if image_path:
            img_bytes, mime_type = self._load_image_bytes(image_path)
            contents = [
                types.Part.from_bytes(data=img_bytes, mime_type=mime_type),
                types.Part.from_text(text=prompt),
            ]
        else:
            contents = prompt

        # Build ordered model list: preferred first, fallback second
        preferred = self.config.model or _GEMINI_DEFAULT_MODEL
        model_queue = (
            [preferred] if preferred == _GEMINI_FALLBACK_MODEL
            else [preferred, _GEMINI_FALLBACK_MODEL]
        )
        model_idx = 0

        for attempt in range(self.config.gemini_max_retries):
            api_key = next(self._key_cycle)
            current_model = model_queue[model_idx]
            try:
                self._rate_limiter.wait()
                client = genai.Client(api_key=api_key)
                response = client.models.generate_content(
                    model=current_model,
                    contents=contents,
                )
                return response.text

            except Exception as exc:  # noqa: BLE001 — broad catch by design
                if self._rate_limiter.is_rate_limit_error(exc):
                    if attempt < self.config.gemini_max_retries - 1:
                        self._rate_limiter.backoff_wait(attempt)
                        # Immediately rotate key on next iteration via cycle
                        continue
                    raise RuntimeError(
                        f"Gemini rate limit exceeded after "
                        f"{self.config.gemini_max_retries} retries."
                    ) from exc

                if self._rate_limiter.is_model_error(exc) and model_idx < len(model_queue) - 1:
                    model_idx += 1
                    logger.warning(
                        "Model '%s' unavailable; retrying with fallback '%s'.",
                        current_model,
                        model_queue[model_idx],
                    )
                    continue

                # Unrecoverable error — re-raise immediately
                raise

        raise RuntimeError(
            f"Gemini call failed after {self.config.gemini_max_retries} attempts."
        )

    def _call_openai(self, prompt: str, *, image_path: str | None = None) -> str:
        """Call the OpenAI Chat Completions API.

        When *image_path* is provided the request uses a multimodal content
        list (image URL as base64 data URI + text).
        """
        try:
            from openai import OpenAI  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError(
                "openai package not installed. Run: pip install openai"
            ) from exc

        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        model = self.config.model or "gpt-4o"

        if image_path:
            img_bytes, mime_type = self._load_image_bytes(image_path)
            b64 = base64.b64encode(img_bytes).decode()
            content: list[dict] = [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{b64}"},
                },
                {"type": "text", "text": prompt},
            ]
        else:
            content = [{"type": "text", "text": prompt}]

        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": content}],
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )
        return response.choices[0].message.content or ""

    def _call_anthropic(self, prompt: str, *, image_path: str | None = None) -> str:
        """Call the Anthropic Messages API.

        When *image_path* is provided the request includes a base64-encoded
        image block followed by the text prompt.
        """
        try:
            import anthropic as ant  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError(
                "anthropic package not installed. Run: pip install anthropic"
            ) from exc

        client = ant.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        model = self.config.model or "claude-3-5-sonnet-20241022"

        if image_path:
            img_bytes, mime_type = self._load_image_bytes(image_path)
            b64 = base64.b64encode(img_bytes).decode()
            content: list[dict] = [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime_type,
                        "data": b64,
                    },
                },
                {"type": "text", "text": prompt},
            ]
        else:
            content = [{"type": "text", "text": prompt}]

        message = client.messages.create(
            model=model,
            max_tokens=self.config.max_tokens,
            messages=[{"role": "user", "content": content}],
        )
        return str(message.content[0].text)  # type: ignore[index]

    # ------------------------------------------------------------------
    # Mock response generator
    # ------------------------------------------------------------------

    def _mock_response(self, item: BenchmarkItem, prompt_type: str) -> str:
        """Return deterministic mock HTML seeded by item ID and prompt type.

        The seed ensures reproducibility across runs.  With_Spec prompts have
        a higher probability of producing error-free JavaScript to reflect the
        expected advantage of detailed specifications.

        Pass-rate targets:
            * With_Spec — Easy 70%, Medium 65%, Hard 60%
            * No_Spec  — Easy 45%, Medium 40%, Hard 35%
        """
        seed = int(hashlib.md5(f"{item.id}:{prompt_type}".encode()).hexdigest(), 16) % (
            2**31
        )
        rng = random.Random(seed)

        script_block = {
            "Easy": self._mock_script_easy(rng, prompt_type),
            "Medium": self._mock_script_medium(rng, prompt_type),
            "Hard": self._mock_script_hard(rng, prompt_type),
        }[item.complexity]

        badge_colour = "#22C55E" if prompt_type == "With_Spec" else "#F97316"
        friendly_name = item.benchmark_name.replace("-", "&#8209;")

        return (
            f"<!DOCTYPE html>\n"
            f"<html lang='en'>\n"
            f"<head>\n"
            f"  <meta charset='UTF-8'>\n"
            f"  <meta name='viewport' content='width=device-width, initial-scale=1.0'>\n"
            f"  <title>{friendly_name} — {item.complexity} — {prompt_type}</title>\n"
            f"  <style>\n"
            f"    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}\n"
            f"    body {{ font-family: system-ui, -apple-system, sans-serif; background: #F3F4F6;\n"
            f"            display: flex; justify-content: center; padding: 2rem; }}\n"
            f"    .card {{ background: #fff; border-radius: 12px; padding: 2rem;\n"
            f"             max-width: 720px; width: 100%; box-shadow: 0 2px 8px rgba(0,0,0,.08); }}\n"
            f"    .badge {{ display: inline-block; padding: .25rem .75rem; border-radius: 999px;\n"
            f"              font-size: .75rem; font-weight: 600; color: #fff;\n"
            f"              background: {badge_colour}; margin-bottom: 1rem; }}\n"
            f"    h1 {{ font-size: 1.5rem; color: #111827; margin-bottom: .5rem; }}\n"
            f"    p  {{ color: #6B7280; line-height: 1.6; margin-bottom: .5rem; }}\n"
            f"    code {{ font-size: .8rem; background: #F9FAFB; padding: .1rem .4rem;\n"
            f"            border-radius: 4px; border: 1px solid #E5E7EB; }}\n"
            f"  </style>\n"
            f"</head>\n"
            f"<body>\n"
            f"  <div class='card'>\n"
            f"    <span class='badge'>{prompt_type.replace('_', ' ')}</span>\n"
            f"    <h1>{friendly_name}</h1>\n"
            f"    <p>Complexity: <strong>{item.complexity}</strong> &nbsp;|&nbsp; "
            f"ID: <code>{item.id}</code></p>\n"
            f"    {script_block}\n"
            f"  </div>\n"
            f"</body>\n"
            f"</html>"
        )

    @staticmethod
    def _mock_script_easy(rng: random.Random, prompt_type: str) -> str:
        threshold = 0.70 if prompt_type == "With_Spec" else 0.45
        if rng.random() < threshold:
            # Valid — no JS errors
            return (
                "<p>Component rendered successfully.</p>\n"
                "  <script>\n"
                "    document.addEventListener('DOMContentLoaded', () => {\n"
                "      console.log('Easy component loaded.');\n"
                "    });\n"
                "  </script>"
            )
        # ReferenceError on load
        return (
            "<p>Component rendered.</p>\n"
            "  <script>\n"
            "    undeclaredFunction();\n"
            "  </script>"
        )

    @staticmethod
    def _mock_script_medium(rng: random.Random, prompt_type: str) -> str:
        threshold = 0.65 if prompt_type == "With_Spec" else 0.40
        if rng.random() < threshold:
            # Valid DOM manipulation
            return (
                "<ul id='item-list'></ul>\n"
                "  <script>\n"
                "    const items = ['Alpha', 'Beta', 'Gamma', 'Delta'];\n"
                "    const list = document.getElementById('item-list');\n"
                "    items.forEach(name => {\n"
                "      const li = document.createElement('li');\n"
                "      li.textContent = name;\n"
                "      list.appendChild(li);\n"
                "    });\n"
                "  </script>"
            )
        # Undefined function call
        return (
            "<div id='chart-container'></div>\n"
            "  <script>\n"
            "    const rawData = fetchChartData();\n"
            "    renderBarChart('#chart-container', rawData);\n"
            "  </script>"
        )

    @staticmethod
    def _mock_script_hard(rng: random.Random, prompt_type: str) -> str:
        threshold = 0.60 if prompt_type == "With_Spec" else 0.35
        if rng.random() < threshold:
            # Valid class-based app
            return (
                "<div id='app-root'></div>\n"
                "  <script>\n"
                "    class MiniApp {\n"
                "      constructor(rootId) {\n"
                "        this.root = document.getElementById(rootId);\n"
                "        this.state = { count: 0 };\n"
                "      }\n"
                "      render() {\n"
                "        this.root.innerHTML = "
                "`<p>App running — state: ${JSON.stringify(this.state)}</p>`;\n"
                "      }\n"
                "    }\n"
                "    new MiniApp('app-root').render();\n"
                "  </script>"
            )
        # Null dereference — canvas element does not exist in DOM
        return (
            "<div id='canvas-wrapper'></div>\n"
            "  <script>\n"
            "    const canvas = document.getElementById('main-canvas');\n"
            "    const ctx = canvas.getContext('2d');  // TypeError: null\n"
            "    ctx.fillStyle = '#4F46E5';\n"
            "    ctx.fillRect(0, 0, 300, 150);\n"
            "  </script>"
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _check_key_and_maybe_mock(self) -> bool:
        """Return ``True`` (→ mock mode) when the required API key is absent."""
        provider = self.config.provider
        if provider == "google":
            keys = self._collect_gemini_keys()
            if not keys:
                logger.warning(
                    "No GEMINI_API_KEY* environment variables found. "
                    "Switching to mock mode automatically."
                )
                return True
        elif provider == "openai":
            if not os.getenv("OPENAI_API_KEY"):
                logger.warning(
                    "OPENAI_API_KEY not set. Switching to mock mode automatically."
                )
                return True
        elif provider == "anthropic":
            if not os.getenv("ANTHROPIC_API_KEY"):
                logger.warning(
                    "ANTHROPIC_API_KEY not set. Switching to mock mode automatically."
                )
                return True
        return False

    @staticmethod
    def _collect_gemini_keys() -> list[str]:
        """Collect all available Gemini API keys from the environment.

        Checks ``GEMINI_API_KEY`` (primary) and ``GEMINI_API_KEY_1`` through
        ``GEMINI_API_KEY_9`` to support multi-key rotation.

        Returns:
            A de-duplicated ordered list of non-empty key strings.
        """
        keys: list[str] = []
        primary = os.getenv("GEMINI_API_KEY", "").strip()
        if primary:
            keys.append(primary)
        for i in range(1, 10):
            k = os.getenv(f"GEMINI_API_KEY_{i}", "").strip()
            if k and k not in keys:
                keys.append(k)
        return keys

    def _save_artifact(self, item_id: str, prompt_type: str, code: str) -> Path:
        """Write *code* to ``artifacts/{item_id}_{prompt_type}.html``."""
        path = self._artifacts_dir / f"{item_id}_{prompt_type}.html"
        path.write_text(code, encoding="utf-8")
        return path
