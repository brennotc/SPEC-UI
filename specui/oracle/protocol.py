"""Protocolo dos oráculos funcionais (instrumento de medida no estilo WebGen-Bench).

Cada caso é um par (Task, Expected Result) executado por um script Playwright DETERMINÍSTICO,
escrito pelo pesquisador antes do experimento. Não há agente nem juiz: o resultado de um caso é
YES / PARTIAL / NO, calculado a partir das asserções que o próprio script registra:

    YES      todas as asserções pontuadas passaram (há ao menos uma)
    PARTIAL  ao menos uma passou e ao menos uma falhou
    NO       nenhuma passou, OU uma exceção inesperada escapou, OU uma pré-condição falhou
             (`blocked=True`: o caso não pôde ser concluído; vale 0, fica no denominador)

As asserções NUNCA levantam exceção: um locator que não achou nada vira asserção falha, o caso
segue, e "elemento presente mas inerte" (PARTIAL) se distingue de "elemento ausente" (NO).
Asserções PENDING (decisão do pesquisador ainda aberta) ficam fora do numerador e do denominador.
"""

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeout

Level = Literal["A", "B"]
Status = Literal["pass", "fail", "pending"]
Outcome = Literal["YES", "PARTIAL", "NO"]

# Erros que o app não causa de verdade: o navegador sem interação do usuário recusa tocar áudio.
_AUTOPLAY_NOISE = re.compile(r"NotAllowedError|AbortError|play\(\) failed|user didn't interact|autoplay", re.IGNORECASE)


class BlockedError(Exception):
    """Pré-condição não atendida: o caso não pode ser concluído (outcome NO, blocked=True)."""


@dataclass
class AssertionRecord:
    name: str
    status: Status
    detail: str = ""
    pending_ref: str | None = None


def _first_line(exc: BaseException) -> str:
    text = str(exc).strip().splitlines()
    return f"{type(exc).__name__}: {text[0] if text else ''}"[:240]


class Checks:
    """Registrador de asserções entregue a cada caso."""

    def __init__(self, page: Page, page_errors: list[str] | None = None) -> None:
        self.page = page
        self._page_errors = page_errors if page_errors is not None else []
        self.records: list[AssertionRecord] = []

    # ------------------------------------------------------------------ registro

    def ok(self, name: str, condition: Any, detail: str = "") -> bool:
        """Asserção imediata (sem espera)."""
        passed = bool(condition)
        self.records.append(AssertionRecord(name, "pass" if passed else "fail", "" if passed else detail))
        return passed

    def eventually(self, name: str, fn: Callable[[], Any], detail: str = "") -> bool:
        """Asserção com espera: `fn` usa `expect(...)` do Playwright. Falha/timeout vira asserção falha."""
        try:
            fn()
        except (AssertionError, PlaywrightTimeout, PlaywrightError) as exc:
            self.records.append(AssertionRecord(name, "fail", detail or _first_line(exc)))
            return False
        self.records.append(AssertionRecord(name, "pass"))
        return True

    def act(self, name: str, fn: Callable[[], Any]) -> bool:
        """Ação do usuário (clicar, digitar, arrastar). Se falhar, é uma asserção falha, não exceção."""
        try:
            fn()
        except (AssertionError, PlaywrightTimeout, PlaywrightError, ValueError) as exc:
            self.records.append(AssertionRecord(name, "fail", _first_line(exc)))
            return False
        self.records.append(AssertionRecord(name, "pass"))
        return True

    def require(self, name: str, condition: Any, detail: str = "") -> None:
        """Pré-condição: registra a asserção e, se falhar, interrompe o caso (NO, blocked)."""
        if not self.ok(name, condition, detail):
            raise BlockedError(name)

    def advance(self, ms: int) -> bool:
        """Avança o relógio falso disparando TODOS os timers vencidos (`run_for`, não `fast_forward`:
        este dispara cada timer no máximo uma vez). Uma exceção lançada dentro de um callback do app
        é relançada pelo Playwright; aqui ela vira erro de página (`js_errors`) e o caso segue."""
        try:
            self.page.clock.run_for(ms)
        except PlaywrightError as exc:
            message = str(exc).removeprefix("Clock.run_for: ").strip()
            self._page_errors.append(message.splitlines()[0] if message else "erro em callback de timer")  # sem o stack
            return False
        return True

    def pending(self, name: str, ref: str, detail: str = "") -> None:
        """Asserção cuja regra depende de uma decisão aberta (PD-*): não pontua."""
        self.records.append(AssertionRecord(name, "pending", detail, pending_ref=ref))

    # ------------------------------------------------------------------ consulta

    @property
    def scored(self) -> list[AssertionRecord]:
        return [r for r in self.records if r.status in ("pass", "fail")]

    @property
    def n_pass(self) -> int:
        return sum(r.status == "pass" for r in self.records)

    @property
    def n_fail(self) -> int:
        return sum(r.status == "fail" for r in self.records)

    def failed(self) -> list[str]:
        return [f"{r.name} :: {r.detail}" if r.detail else r.name for r in self.records if r.status == "fail"]

    def js_errors(self) -> list[str]:
        """Exceções não tratadas da página (cada uma uma vez), sem o ruído de autoplay de áudio."""
        return list(dict.fromkeys(e for e in self._page_errors if not _AUTOPLAY_NOISE.search(e)))


def classify(records: list[AssertionRecord], crashed: bool = False, blocked: bool = False) -> Outcome:
    """Regra determinística YES / PARTIAL / NO."""
    if crashed or blocked:
        return "NO"
    scored = [r for r in records if r.status in ("pass", "fail")]
    if not scored:
        return "NO"
    n_fail = sum(r.status == "fail" for r in scored)
    if n_fail == 0:
        return "YES"
    return "NO" if n_fail == len(scored) else "PARTIAL"


# ----------------------------------------------------------------------------- registro de casos


@dataclass(frozen=True)
class CaseSpec:
    id: str
    requirements: tuple[str, ...]
    level: Level
    task: str  # passos (o "Task" do WebGen-Bench)
    expected: str  # o "Expected Result"
    task_id: str = ""
    tags: tuple[str, ...] = ()
    pending: str | None = None  # PD-*: o caso é listado mas não executado (fora de N_total)
    uses_clock: bool = True
    fixed_now: str | None = None
    fn: Callable[[Page, Checks], None] | None = field(default=None, compare=False)


REGISTRY: dict[str, list[CaseSpec]] = {}


def case(
    id: str,
    *,
    requirements: list[str] | tuple[str, ...],
    level: Level,
    task: str,
    expected: str,
    tags: tuple[str, ...] = (),
    pending: str | None = None,
    uses_clock: bool = True,
    fixed_now: str | None = None,
) -> Callable[[Callable[[Page, Checks], None]], Callable[[Page, Checks], None]]:
    """Registra um caso. O pacote da tarefa vem do módulo (`oracles.<tarefa>.level_a`)."""

    def decorator(fn: Callable[[Page, Checks], None]) -> Callable[[Page, Checks], None]:
        parts = fn.__module__.split(".")
        if len(parts) < 3 or parts[0] != "oracles":
            raise ValueError(f"caso '{id}' fora de oracles.<tarefa>.<módulo>: {fn.__module__}")
        task_id = parts[1]
        REGISTRY.setdefault(task_id, []).append(
            CaseSpec(id=id, requirements=tuple(requirements), level=level, task=task, expected=expected,
                     task_id=task_id, tags=tags, pending=pending, uses_clock=uses_clock, fixed_now=fixed_now, fn=fn)
        )
        return fn

    return decorator


def now_ms() -> float:
    return time.monotonic() * 1000
