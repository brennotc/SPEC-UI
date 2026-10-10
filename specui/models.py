"""Modelos de dados do SPEC-UI.

Convenção: toda métrica não calculada fica `None` (com o motivo em `errors` do RunRecord),
nunca 0. A imputação ITT (nota 0 para execuções que falharam) é feita na análise.
"""

import os
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from specui.clock import FIXED_NOW

Modality = Literal["text", "multimodal"]
Difficulty = Literal["easy", "medium", "hard"]
RunKind = Literal["pilot", "main", "smoke"]  # smoke: gerador simulado, results/smoke/ (nunca entra em evaluate/analyze)
Provider = Literal["google", "mock"]
PromptKind = Literal["no_spec", "with_spec", "free"]
MaterialShown = Literal["image", "image+brief", "image+prototype"]
RunStatus = Literal[
    "done",
    "format_failure",
    "contract_failure",
    "nonexecutable",
    "api_error",
    "refusal",
    "truncated",
    "metric_error",
    "model_mismatch",
]

DIFFICULTIES: tuple[str, ...] = ("easy", "medium", "hard")

# Status que entram na análise ITT (nota funcional vale 0 quando não houve render).
ITT_STATUSES: frozenset[str] = frozenset(
    {"done", "format_failure", "contract_failure", "nonexecutable", "refusal", "truncated"}
)
# Falhas de infraestrutura / modelo trocado: fora de qualquer conjunto de análise.
EXCLUDED_STATUSES: frozenset[str] = frozenset({"api_error", "metric_error", "model_mismatch"})


# --------------------------------------------------------------------------- tarefas e prompts


class Task(BaseModel):
    id: str
    difficulty: Difficulty
    md_path: str
    prompt_text: str  # só a seção "## Prompt"
    spec_text: str  # só a seção "## Specification"
    image_path: str  # PNG exportado do Figma; obrigatório
    image_size: tuple[int, int]
    image_sha256: str
    figma_node_id: str | None = None


class PromptSource(BaseModel):
    kind: PromptKind
    prompt_id: str  # "easy_pomodoro/no_spec" | "free:<coleta>/<participante>/<n>"
    task_id: str
    text: str
    text_sha256: str
    # Só para kind == "free":
    collection_id: str | None = None
    participant_id: str | None = None  # id sequencial anônimo (p001...)
    intended_modality: Modality | None = None
    material_shown: MaterialShown | None = None
    collected_at: str | None = None  # só a data (AAAA-MM-DD)
    instrument_version: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)  # perfil em faixas amplas


# --------------------------------------------------------------------------- configuração


def _is_alias(model_id: str) -> bool:
    return bool(re.search(r"(latest|preview|exp)\b", model_id, flags=re.IGNORECASE))


class Generator(BaseModel):
    provider: Provider
    model_id: str
    temperature: float | None = None  # None = padrão do provedor (nunca 0)
    max_output_tokens: int = 32768
    thinking: dict[str, Any] = Field(default_factory=dict)
    request_delay_s: float = 2.0
    max_retries: int = 5
    # Só provider == "mock": que comportamento simular (exercita os caminhos de falha).
    mock_variant: Literal[
        "ok", "broken", "no_format", "no_contract", "truncated", "refusal", "model_mismatch"
    ] = "ok"

    @field_validator("temperature")
    @classmethod
    def _temperature_not_zero(cls, v: float | None) -> float | None:
        if v is not None and v <= 0:
            raise ValueError("temperature deve ser null (padrão do provedor) ou > 0; nunca 0")
        return v

    @model_validator(mode="after")
    def _no_alias(self) -> "Generator":
        if self.provider != "mock" and _is_alias(self.model_id):
            raise ValueError(
                f"model_id '{self.model_id}' parece um alias (latest/preview/exp); "
                "fixe o id exato da versão"
            )
        return self

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.model_id}"


def default_workspace_dir() -> str:
    """Pasta de build do harness. No Windows, um caminho CURTO (o limite MAX_PATH quebra o node_modules em caminhos longos);
    nos demais sistemas, o cache do usuário. Sobrescreva com `workspace_dir` no YAML."""
    return "C:/specui-work" if os.name == "nt" else "~/.cache/specui-work"


class AnalysisConfig(BaseModel):
    # Margem do TOST entre modelos. Sem default: None => o teste de equivalência não roda.
    equivalence_margin: float | None = None
    n_boot: int = 10_000
    n_perm: int = 10_000
    alpha: float = 0.05
    seed: int = 20260101


_PROMPT_SOURCE_RE = re.compile(r"^(no_spec|with_spec|free:[A-Za-z0-9_.-]+)$")


class RunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_kind: RunKind = "main"
    repetitions: int = 5
    free_repetitions: int = 3
    tasks: list[str] = Field(default_factory=lambda: list(DIFFICULTIES))  # dificuldades (easy, medium, hard) e/ou ids (easy_pomodoro)
    modalities: list[Modality] = Field(default_factory=lambda: ["text", "multimodal"])
    prompt_sources: list[str] = Field(default_factory=lambda: ["no_spec", "with_spec"])
    free_modalities: Literal["intended", "both"] = "intended"
    generators: list[Generator]
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    base_seed: int = 20260101

    # Diretórios: relativos a repo_root (workspace_dir e model_cache_dir podem ser absolutos).
    repo_root: str = "."
    benchmarks_dir: str = "benchmarks"
    references_dir: str = "references/figma"
    oracles_dir: str = "oracles"
    scaffold_dir: str = "scaffold/angular-base"
    results_dir: str = "results"
    workspace_dir: str = Field(default_factory=lambda: default_workspace_dir())
    model_cache_dir: str = "~/.cache/specui-models"

    # Harness
    build_timeout_s: int = 180
    build_configuration: Literal["development", "production"] = "development"
    viewport: tuple[int, int] | None = None  # None = tamanho do PNG da tarefa
    render_settle_ms: int = 800
    clock_epoch_iso: str = FIXED_NOW  # fixo: é parte do instrumento (ver specui/clock.py)
    block_network: bool = True

    # Métricas
    enable_embeddings: bool = True
    enable_ocr_fallback: bool = False
    oracle_levels: list[Literal["A", "B"]] = Field(default_factory=lambda: ["A", "B"])

    @field_validator("clock_epoch_iso")
    @classmethod
    def _clock_is_the_instrument_clock(cls, value: str) -> str:
        if value != FIXED_NOW:
            raise ValueError(
                f"clock_epoch_iso deve ser {FIXED_NOW}: o relógio é parte do instrumento (os oráculos criam tarefas para "
                "hoje/amanhã a partir desta data); mudá-lo exige nova versão do oráculo, não só da configuração"
            )
        return value

    @field_validator("repetitions", "free_repetitions", "build_timeout_s")
    @classmethod
    def _positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("deve ser >= 1")
        return v

    @field_validator("tasks")
    @classmethod
    def _tasks_are_difficulties_or_ids(cls, v: list[str]) -> list[str]:
        """Aceita dificuldade ou id de tarefa (o mesmo que `load_tasks` aceita); a existência do id é conferida ao carregar."""
        if not v:
            raise ValueError("tasks vazio")
        for item in v:
            if item not in DIFFICULTIES and not re.fullmatch(r"[a-z][a-z0-9_]*", item):
                raise ValueError(f"tarefa inválida: '{item}' (use easy|medium|hard ou o id de uma tarefa, ex.: easy_pomodoro)")
        if len(set(v)) != len(v):
            raise ValueError("tasks com itens repetidos")
        return v

    @field_validator("prompt_sources")
    @classmethod
    def _valid_sources(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("prompt_sources não pode ser vazio")
        for item in v:
            if not _PROMPT_SOURCE_RE.match(item):
                raise ValueError(
                    f"prompt_source inválida: '{item}' (use no_spec, with_spec ou free:<id>)"
                )
        if len(set(v)) != len(v):
            raise ValueError("prompt_sources com itens repetidos")
        return v

    @field_validator("generators")
    @classmethod
    def _valid_generators(cls, v: list[Generator]) -> list[Generator]:
        if not v:
            raise ValueError("defina ao menos 1 gerador (k >= 2 para o experimento principal)")
        keys = [g.key for g in v]
        if len(set(keys)) != len(keys):
            raise ValueError(f"geradores repetidos: {keys}")
        return v

    def path(self, name: str) -> Path:
        """Resolve um diretório da config relativo a `repo_root`."""
        value = Path(getattr(self, name)).expanduser()
        return value if value.is_absolute() else (Path(self.repo_root) / value).resolve()


# --------------------------------------------------------------------------- execução


class Cell(BaseModel):
    task_id: str
    prompt_source: PromptSource
    modality: Modality
    rep: int
    provider: Provider
    model_id: str

    @property
    def key(self) -> str:
        return (
            f"{self.prompt_source.prompt_id}|{self.modality}|"
            f"{self.provider}:{self.model_id}|r{self.rep}"
        )


class ScaffoldInfo(BaseModel):
    version: str
    lock_sha256: str
    tree_sha256: str | None = None  # hash dos arquivos do scaffold (sem node_modules)
    angular_version: str
    packages: dict[str, str]  # pacote -> versão exata (o que o modelo pode importar)


class PromptPackage(BaseModel):
    system: str
    user_text: str
    image_path: str | None = None
    image_sha256: str | None = None
    modality: Modality
    envelope_version: str
    envelope_sha256: str
    prompt_sha256: str


# --------------------------------------------------------------------------- métricas


class ExecMetrics(BaseModel):
    format_ok: bool = False
    files_accepted: int = 0
    files_rejected: list[tuple[str, str]] = Field(default_factory=list)  # (caminho, motivo)
    contract_ok: bool | None = None  # src/app/app.ts exporta App (definido se format_ok)
    build_ok: bool | None = None  # definido se contract_ok
    build_timed_out: bool = False
    build_time_s: float | None = None
    build_stdout_path: str | None = None
    build_stderr_path: str | None = None
    build_error_messages: list[str] = Field(default_factory=list)
    render_ok: bool | None = None
    # build_ok and render_ok; definido só quando format_ok and contract_ok.
    executable: bool | None = None


class Design2CodeMetrics(BaseModel):
    n_ref_blocks: int
    n_gen_blocks: int
    n_matched: int
    n_merged_ref: int = 0
    n_merged_gen: int = 0
    block_match: float | None = None
    text: float | None = None
    position: float | None = None
    color: float | None = None
    clip_inpainted: float | None = None
    reference_source: Literal["figma", "ocr"] = "figma"
    pairs_path: str | None = None


class EmbeddingMetrics(BaseModel):
    ves_dinov2: float | None = None
    mae: float | None = None
    ssim: float | None = None  # secundária
    dinov2_model: str = "facebook/dinov2-base"
    clip_model: str = "openai/clip-vit-base-patch32"


class CodeQualityMetrics(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    rur: float | None = None
    apr: float | None = None
    fu: float | None = None
    bc: float | None = None
    str_: float | None = Field(default=None, alias="str")
    avu: float | None = None
    isr: float | None = None
    ccr: float | None = None
    counts: dict[str, int] = Field(default_factory=dict)  # numeradores/denominadores


class CaseOutcome(BaseModel):
    case_id: str
    level: Literal["A", "B"]
    outcome: Literal["YES", "PARTIAL", "NO", "PENDING"]
    blocked: bool = False  # pré-condição não atendida: o caso não pôde ser concluído (vale NO)
    n_pass: int = 0
    n_total: int = 0  # asserções pontuadas (pass + fail); PENDING e passos (ações/pré-condições que deram certo) ficam de fora
    n_steps: int = 0  # passos executados com sucesso (não pontuam)
    requirements: list[str] = Field(default_factory=list)
    failed: list[str] = Field(default_factory=list)  # "<asserção> :: <detalhe>" das que falharam
    error: str | None = None  # exceção inesperada (bug do oráculo ou do app), não falha de asserção
    duration_ms: int = 0


class FunctionalMetrics(BaseModel):
    accuracy_a: float | None = None
    # Só requisitos compatíveis com o material mostrado; = accuracy_a para no_spec/with_spec.
    accuracy_a_restricted: float | None = None
    accuracy_b: float | None = None
    cases: list[CaseOutcome] = Field(default_factory=list)
    suite_sha256: str | None = None
    suite_git_tag: str | None = None


class TechnicalMetrics(BaseModel):
    console_errors: list[str] = Field(default_factory=list)
    console_error_count: int = 0
    blocked_requests: list[str] = Field(default_factory=list)
    axe_violations: dict[str, int] = Field(default_factory=dict)  # critical/serious/moderate/minor
    axe_report_path: str | None = None


class StackRequests(BaseModel):
    react: bool = False
    vue: bool = False
    svelte: bool = False
    next: bool = False
    html_puro: bool = False
    bootstrap: bool = False
    jquery: bool = False
    outros: list[str] = Field(default_factory=list)

    @property
    def any(self) -> bool:
        return bool(
            self.react
            or self.vue
            or self.svelte
            or self.next
            or self.html_puro
            or self.bootstrap
            or self.jquery
            or self.outros
        )


class RequirementCoverage(BaseModel):
    total: float | None = None
    by_info_source: dict[str, float] = Field(default_factory=dict)  # image/behavior/spec_only


class InputSpecMetrics(BaseModel):
    """Calculado para todo prompt (no_spec, with_spec e free)."""

    chars: int
    words: int
    constraint_density: dict[str, int]  # hex, px, defaults, aria, html_tags
    requirement_coverage: RequirementCoverage = Field(default_factory=RequirementCoverage)
    structure_markers: dict[str, int]  # lists, numbering, headings, code_blocks, type_decls
    image_references: int = 0
    stack_requests: StackRequests = Field(default_factory=StackRequests)
    envelope_chars: int = 0


class CostMetrics(BaseModel):
    prompt_tokens: int | None = None  # contagem só do texto (system + user)
    input_tokens: int | None = None
    output_tokens: int | None = None
    thoughts_tokens: int | None = None
    latency_ms: int | None = None


class RunRecord(BaseModel):
    run_id: str
    run_kind: RunKind
    cell_key: str
    task_id: str
    difficulty: Difficulty
    prompt_kind: PromptKind
    prompt_id: str
    material_shown: MaterialShown | None = None  # só prompts livres
    modality: Modality
    rep: int
    created_at: str

    provider: Provider
    model_id_requested: str
    model_id_returned: str | None = None
    finish_reason: str | None = None  # como o provedor encerrou a resposta (STOP, MAX_TOKENS, SAFETY, RECITATION, OTHER...)
    temperature: float | None = None
    thinking: dict[str, Any] = Field(default_factory=dict)
    seed: int | None = None

    prompt_sha256: str
    image_sha256: str | None = None
    envelope_sha256: str
    envelope_version: str
    scaffold_version: str | None = None
    scaffold_lock_sha256: str | None = None
    scaffold_tree_sha256: str | None = None
    repo_commit: str | None = None
    config_sha256: str | None = None
    oracle_suite_tag: str | None = None
    oracle_tree_hash: str | None = None
    oracle_content_sha256: str | None = None
    oracle_dirty: bool | None = None
    pending_sha256: str | None = None
    mention_patterns_sha256: str | None = None
    playwright_version: str | None = None
    browser_version: str | None = None

    paths: dict[str, str] = Field(default_factory=dict)
    exec: ExecMetrics = Field(default_factory=ExecMetrics)
    design2code: Design2CodeMetrics | None = None
    embeddings: EmbeddingMetrics | None = None
    code_quality: CodeQualityMetrics | None = None
    functional: FunctionalMetrics | None = None
    technical: TechnicalMetrics | None = None
    input_spec: InputSpecMetrics | None = None
    cost: CostMetrics = Field(default_factory=CostMetrics)

    status: RunStatus = "done"
    errors: list[str] = Field(default_factory=list)
