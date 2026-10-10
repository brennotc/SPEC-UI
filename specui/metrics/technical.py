"""Métricas técnicas (erros de console, rede bloqueada, axe) e de custo do pedido."""

from specui.harness.browser import RenderArtifacts
from specui.llm.base import LLMClient, LLMResponse
from specui.models import CostMetrics, PromptPackage, TechnicalMetrics


def compute_technical(render: RenderArtifacts) -> TechnicalMetrics:
    """Erros de console JS (inclui exceções não tratadas), requisições bloqueadas e axe-core."""
    errors = [*render.page_errors, *render.console_errors]
    return TechnicalMetrics(
        console_errors=errors,
        console_error_count=len(errors),
        blocked_requests=list(render.blocked_requests),
        axe_violations=dict(render.axe_violations),
        axe_report_path=render.axe_path,
    )


def compute_cost(pkg: PromptPackage, response: LLMResponse | None, client: LLMClient | None) -> CostMetrics:
    """Tokens e latência. `prompt_tokens` conta só o texto (system + user); a diferença para
    `input_tokens` é o custo da imagem. Entre provedores compare caracteres, não tokens."""
    cost = CostMetrics()
    if client is not None:
        cost.prompt_tokens = client.count_tokens(pkg.system, pkg.user_text)
    if response is not None:
        cost.input_tokens = response.input_tokens
        cost.output_tokens = response.output_tokens
        cost.thoughts_tokens = response.thoughts_tokens
        cost.latency_ms = response.latency_ms
    return cost
