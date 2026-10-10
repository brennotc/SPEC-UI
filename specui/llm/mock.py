"""Cliente simulado. Só existe com `provider: mock`; nunca substitui um provedor em silêncio.

Devolve um projeto Angular mínimo e genérico (specui/llm/mock_bundle: um componente "Olá"),
que NÃO é implementação de nenhuma tarefa. Serve para exercitar o pipeline sem API e, pelas
variantes, cada caminho de falha: build quebrado, sem formato, sem contrato, truncado, recusa
e modelo trocado.
"""

from pathlib import Path

from specui.llm.base import LLMResponse
from specui.models import Generator, PromptPackage

_BUNDLE_DIR = Path(__file__).parent / "mock_bundle"
_FILES = {"src/app/app.ts": "ts", "src/app/app.html": "html", "src/app/app.css": "css"}


def _read(path: str) -> str:
    return (_BUNDLE_DIR / Path(path).name).read_text(encoding="utf-8")


def _block(path: str, content: str) -> str:
    return f"```{_FILES[path]} file={path}\n{content.rstrip()}\n```\n"


class MockClient:
    def __init__(self, generator: Generator) -> None:
        self.generator = generator

    def _body(self) -> str:
        variant = self.generator.mock_variant
        files = {p: _read(p) for p in _FILES}
        if variant == "broken":  # erro de sintaxe: o build tem que falhar
            files["src/app/app.ts"] = files["src/app/app.ts"].rstrip()[:-1]  # tira o último "}"
        if variant == "no_contract":  # sem `export class App`
            files["src/app/app.ts"] = files["src/app/app.ts"].replace("class App", "class Main")
        if variant == "no_format":
            return "Aqui está a interface pedida: use um componente com um título e um botão."
        return "".join(_block(p, c) for p, c in files.items())

    def generate(self, pkg: PromptPackage, seed: int | None) -> LLMResponse:
        variant = self.generator.mock_variant
        returned = "mock-other" if variant == "model_mismatch" else self.generator.model_id
        in_tokens = (len(pkg.system) + len(pkg.user_text)) // 4
        if variant == "refusal":
            return LLMResponse(
                model_returned=returned, input_tokens=in_tokens, output_tokens=0,
                latency_ms=1, finish_reason="refusal", refused=True, refusal_detail="mock",
            )
        text = self._body()
        truncated = variant == "truncated"
        if truncated:
            text = text[: len(text) // 2]
        return LLMResponse(
            text=text,
            model_returned=returned,
            input_tokens=in_tokens,
            output_tokens=len(text) // 4,
            latency_ms=1,
            finish_reason="MAX_TOKENS" if truncated else "STOP",
            truncated=truncated,
        )

    def count_tokens(self, system: str, user_text: str) -> int | None:
        return (len(system) + len(user_text)) // 4

    def check_model(self) -> str:
        return self.generator.model_id
