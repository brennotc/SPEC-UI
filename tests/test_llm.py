"""Clientes de LLM com SDK simulado (nenhuma chamada de rede)."""

from types import SimpleNamespace

import pytest

from specui.codegen import parse_bundle
from specui.llm import (
    ConfigurationError,
    DailyQuotaExceededError,
    GeminiClient,
    LLMError,
    MockClient,
    make_client,
    model_matches,
)
from specui.llm.base import KeyRing, RateLimiter, collect_keys
from specui.models import Generator, PromptPackage
from specui.prompting import build_messages
from specui.prompts import make_standard_source

NO_SLEEP = lambda s: None


@pytest.fixture
def pkg(tasks, scaffold) -> PromptPackage:
    return build_messages(tasks[0], make_standard_source(tasks[0], "no_spec"), "text", scaffold)


@pytest.fixture
def pkg_image(tasks, scaffold) -> PromptPackage:
    return build_messages(tasks[0], make_standard_source(tasks[0], "no_spec"), "multimodal", scaffold)


# ----------------------------------------------------------------- verificação do modelo


@pytest.mark.parametrize(
    "requested, returned, ok",
    [
        ("gemini-2.5-flash", "gemini-2.5-flash", True),
        ("gemini-2.5-flash", "models/gemini-2.5-flash", True),
        ("gemini-2.5-flash", "gemini-2.5-flash-001", True),
        ("gemini-2.5-flash", "gemini-2.5-flash-lite", False),
        ("gemini-2.5-flash", "gemini-2.5-flash-preview-05-20", False),
        ("gemini-2.5-flash", "gemini-2.5-pro", False),
        ("gemini-2.5-flash", None, False),
        ("gemini-3.8-flash", "gemini-3.8-flash", True),
        ("gemini-3.8-flash", "gemini-3.8", False),
    ],
)
def test_model_matches(requested, returned, ok):
    assert model_matches(requested, returned) is ok


# ----------------------------------------------------------------- chaves e limitador


def test_collect_keys_reads_numbered_and_dedupes(monkeypatch):
    for name in ("FOO_KEY", "FOO_KEY_1", "FOO_KEY_2", "FOO_KEY_3", "ALT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FOO_KEY", "a")
    monkeypatch.setenv("FOO_KEY_1", "b")
    monkeypatch.setenv("FOO_KEY_2", "a")  # repetida
    monkeypatch.setenv("FOO_KEY_3", "  ")  # vazia
    monkeypatch.setenv("ALT", "c")
    assert collect_keys("FOO_KEY", ("ALT",)) == ["a", "b", "c"]


def test_key_ring_rotates_and_requires_keys():
    ring = KeyRing(["a", "b"])
    assert ring.current == "a" and ring.rotate() == "b" and ring.rotate() == "a"
    with pytest.raises(ConfigurationError):
        KeyRing([])


def test_rate_limiter_backoff_is_exponential_and_capped():
    lim = RateLimiter(request_delay_s=2.0, max_retries=5)
    assert [lim.backoff_seconds(i) for i in range(4)] == [2.0, 4.0, 8.0, 16.0]
    assert lim.backoff_seconds(20) == 300.0


def test_make_client_never_falls_back_to_mock(monkeypatch):
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    for i in range(1, 10):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
    with pytest.raises(ConfigurationError, match="GEMINI_API_KEY"):
        make_client(Generator(provider="google", model_id="gemini-2.5-flash"))
    assert isinstance(make_client(Generator(provider="mock", model_id="m")), MockClient)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    assert isinstance(make_client(Generator(provider="google", model_id="gemini-2.5-flash")), GeminiClient)


# ----------------------------------------------------------------- Gemini


def _gemini_response(text="ok", finish="STOP", model="gemini-2.5-flash", block=None):
    return SimpleNamespace(
        text=text,
        model_version=model,
        candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name=finish))],
        usage_metadata=SimpleNamespace(prompt_token_count=100, candidates_token_count=50, thoughts_token_count=20),
        prompt_feedback=SimpleNamespace(block_reason=block),
    )


class FakeGemini:
    """Cliente google-genai falso: executa `script` (exceção ou resposta) a cada chamada."""

    def __init__(self, script):
        self.script, self.calls, self.keys_used = list(script), [], []
        self.models = SimpleNamespace(
            generate_content=self._generate,
            count_tokens=lambda model, contents: SimpleNamespace(total_tokens=321),
            get=lambda model: SimpleNamespace(name=f"models/{model}"),
        )

    def _generate(self, model, contents, config):
        self.calls.append(SimpleNamespace(model=model, contents=contents, config=config))
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def _gemini(script, **gen_kwargs):
    fake = FakeGemini(script)
    gen = Generator(provider="google", model_id="gemini-2.5-flash", request_delay_s=0, max_retries=4,
                    thinking={"thinking_budget": 4096}, **gen_kwargs)

    def factory(key):
        fake.keys_used.append(key)
        return fake

    return GeminiClient(gen, ["k1", "k2"], client_factory=factory, sleep=NO_SLEEP), fake


def test_gemini_generate_maps_response_and_config(pkg):
    client, fake = _gemini([_gemini_response("conteúdo")])
    r = client.generate(pkg, seed=42)
    assert r.text == "conteúdo" and r.model_returned == "gemini-2.5-flash"
    assert (r.input_tokens, r.output_tokens, r.thoughts_tokens) == (100, 50, 20)
    assert r.finish_reason == "STOP" and not r.truncated and not r.refused
    cfg = fake.calls[0].config
    assert cfg.seed == 42 and cfg.max_output_tokens == 32768
    assert cfg.system_instruction == pkg.system
    assert cfg.thinking_config.thinking_budget == 4096
    assert cfg.temperature is None  # padrão do provedor: não enviado
    assert fake.calls[0].contents == pkg.user_text  # sem imagem: só o texto


def test_gemini_sends_image_before_text_when_multimodal(pkg_image):
    client, fake = _gemini([_gemini_response()])
    client.generate(pkg_image, seed=1)
    parts = fake.calls[0].contents
    assert isinstance(parts, list) and len(parts) == 2
    assert parts[0].inline_data.mime_type == "image/png" and parts[0].inline_data.data
    assert parts[1].text == pkg_image.user_text


def test_gemini_truncated_and_refused_flags(pkg):
    client, _ = _gemini([_gemini_response(finish="MAX_TOKENS")])
    assert client.generate(pkg, 1).truncated is True
    client, _ = _gemini([_gemini_response(text="", finish="SAFETY")])
    r = client.generate(pkg, 1)
    assert r.refused is True and r.refusal_detail == "SAFETY"
    client, _ = _gemini([_gemini_response(text="", block="PROHIBITED_CONTENT")])
    assert client.generate(pkg, 1).refused is True


def test_gemini_rate_limit_rotates_key_and_retries(pkg):
    client, fake = _gemini([Exception("429 RESOURCE_EXHAUSTED: rate limit"), _gemini_response("ok")])
    assert client.generate(pkg, 1).text == "ok"
    assert fake.keys_used == ["k1", "k2"]  # rotacionou na 429


DAILY = "429 RESOURCE_EXHAUSTED: Quota exceeded for metric generate_content_free_tier_requests, quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier"
PER_MINUTE = "429 RESOURCE_EXHAUSTED: Quota exceeded for metric generate_content_free_tier_requests, quotaId: GenerateRequestsPerMinutePerProjectPerModel-FreeTier"


def test_gemini_daily_quota_switches_to_the_next_key_and_keeps_going(pkg):
    client, fake = _gemini([Exception(DAILY), _gemini_response("ok")])
    assert client.generate(pkg, 1).text == "ok"
    assert fake.keys_used == ["k1", "k2"] and len(fake.calls) == 2
    # a chave esgotada não volta a ser usada nesta execução, nem pela rotação do limite por minuto
    client.keys.rotate()
    assert client.keys.current == "k2"


def test_gemini_daily_quota_on_every_key_pauses_the_provider(pkg):
    client, fake = _gemini([Exception(DAILY), Exception(DAILY)])
    with pytest.raises(DailyQuotaExceededError, match="todas as 2 chave") as err:
        client.generate(pkg, 1)
    assert err.value.provider == "google" and len(fake.calls) == 2


def test_gemini_per_minute_free_tier_limit_is_not_a_daily_quota(pkg):
    client, _ = _gemini([Exception(PER_MINUTE), _gemini_response("ok")])
    assert client.generate(pkg, 1).text == "ok"  # esperou e rotacionou, sem marcar a chave como esgotada
    assert client.keys.remaining == 2


def test_gemini_model_and_auth_errors_are_configuration_errors(pkg):
    client, _ = _gemini([Exception("404 models/x is not found")])
    with pytest.raises(ConfigurationError, match="indisponível"):
        client.generate(pkg, 1)
    client, _ = _gemini([Exception("400 API key not valid. Please pass a valid API key")])
    with pytest.raises(ConfigurationError, match="credencial"):
        client.generate(pkg, 1)


def test_gemini_transient_then_giving_up_is_llm_error(pkg):
    client, fake = _gemini([Exception("503 UNAVAILABLE")] * 4)
    with pytest.raises(LLMError, match="esgotadas"):
        client.generate(pkg, 1)
    assert len(fake.calls) == 4
    client, _ = _gemini([ValueError("algo inesperado")])
    with pytest.raises(LLMError, match="falha na chamada"):
        client.generate(pkg, 1)


def test_gemini_count_tokens_and_check_model(pkg):
    client, _ = _gemini([])
    assert client.count_tokens(pkg.system, pkg.user_text) == 321
    assert client.check_model() == "gemini-2.5-flash"


def test_gemini_sends_temperature_only_when_set(pkg):
    client, fake = _gemini([_gemini_response()], temperature=0.7)
    client.generate(pkg, 1)
    assert fake.calls[0].config.temperature == 0.7


# ----------------------------------------------------------------- Mock


def _mock(variant="ok"):
    return MockClient(Generator(provider="mock", model_id="mock-1", mock_variant=variant))


def test_mock_ok_roundtrips_through_parser(pkg):
    r = _mock().generate(pkg, 1)
    b = parse_bundle(r.text)
    assert b.format_ok and b.contract_ok and b.rejected == []
    assert {f.path for f in b.files} == {"src/app/app.ts", "src/app/app.html", "src/app/app.css"}
    assert r.model_returned == "mock-1" and not r.truncated and not r.refused


def test_mock_variants_exercise_each_failure_path(pkg):
    assert not parse_bundle(_mock("no_format").generate(pkg, 1).text).format_ok
    b = parse_bundle(_mock("no_contract").generate(pkg, 1).text)
    assert b.format_ok and not b.contract_ok
    b = parse_bundle(_mock("broken").generate(pkg, 1).text)
    assert b.format_ok and b.contract_ok and b.files[0].content.rstrip().endswith("'Mock';")
    t = _mock("truncated").generate(pkg, 1)
    assert t.truncated and t.finish_reason == "MAX_TOKENS"
    assert _mock("refusal").generate(pkg, 1).refused is True
    assert _mock("model_mismatch").generate(pkg, 1).model_returned == "mock-other"


def test_mock_bundle_has_no_task_content(pkg):
    text = _mock().generate(pkg, 1).text.lower()
    assert "pomodoro" not in text and "kanban" not in text


def test_gemini_keeps_one_live_client_per_key():
    """O google-genai fecha a conexão quando o Client é coletado: o cliente precisa ser reaproveitado."""
    from specui.llm.gemini import GeminiClient
    from specui.models import Generator

    made = []

    class FakeModels:
        def get(self, model):
            return type("Info", (), {"name": f"models/{model}"})()

    def factory(key):
        made.append(key)
        return type("C", (), {"models": FakeModels()})()

    client = GeminiClient(Generator(provider="google", model_id="gemini-2.5-flash", request_delay_s=0), ["k1"], factory)
    assert client.check_model() == "gemini-2.5-flash" and client.check_model() == "gemini-2.5-flash"
    assert made == ["k1"]
