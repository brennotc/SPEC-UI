"""Execução das suítes de oráculos: carga, run por caso em contexto limpo, lint e rastreabilidade."""

import importlib
import inspect
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import expect

from specui.clock import FIXED_NOW
from specui.harness.browser import BrowserSession, load_app
from specui.models import CaseOutcome
from specui.oracle.protocol import REGISTRY, BlockedError, CaseSpec, Checks, classify, now_ms
from specui.oracle.requirements import Requirement, load_pending, load_requirements

EXPECT_TIMEOUT_MS = 1500
ACTION_TIMEOUT_MS = 3000
ROOT_TIMEOUT_MS = 10_000

# Espiões instalados em TODA página dos oráculos: contam as chamadas de áudio e impedem que a
# política de autoplay (sem gesto do usuário) vire erro não tratado atribuído ao app.
SPIES_JS = """
(() => {
  window.__specui = { audioPlays: 0, audioContexts: 0 };
  const originalPlay = HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play = function () {
    window.__specui.audioPlays++;
    return Promise.resolve();
  };
  for (const name of ['AudioContext', 'webkitAudioContext']) {
    const Original = window[name];
    if (!Original) continue;
    window[name] = function (...args) { window.__specui.audioContexts++; return new Original(...args); };
    window[name].prototype = Original.prototype;
  }
})();
"""


@dataclass
class Suite:
    task_id: str
    cases: list[CaseSpec]
    root: Path  # oracles/<tarefa>


def _natural(case_id: str) -> list[int | str]:
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", case_id)]


def _purge_modules(task_id: str | None, oracles_dir: Path) -> None:
    """Esquece módulos `oracles*` de outro diretório (ou da tarefa, para recarregar do disco)."""
    pkg = sys.modules.get("oracles")
    foreign = pkg is not None and getattr(pkg, "__file__", None) and Path(pkg.__file__).parent.resolve() != oracles_dir
    fresh = (f"oracles.{task_id}", "oracles.common") if task_id else ()
    for name in list(sys.modules):
        if (name == "oracles" or name.startswith("oracles.")) and (foreign or not fresh or name.startswith(fresh)):
            del sys.modules[name]


def load_suite(oracles_dir: str | Path, task_id: str) -> Suite:
    """Importa `oracles/<tarefa>/level_a.py` e `level_b.py` (os `@case` se registram sozinhos)."""
    oracles_dir = Path(oracles_dir).resolve()
    root = oracles_dir / task_id
    if not root.is_dir():
        raise FileNotFoundError(f"suíte '{task_id}' não encontrada em {oracles_dir}")
    parent = str(oracles_dir.parent)
    if sys.path[:1] != [parent]:  # um `oracles/` de outro diretório (testes) não pode sombrear este
        if parent in sys.path:
            sys.path.remove(parent)
        sys.path.insert(0, parent)
    importlib.invalidate_caches()
    _purge_modules(task_id, oracles_dir)
    REGISTRY.pop(task_id, None)
    for module in ("level_a", "level_b"):
        if (root / f"{module}.py").is_file():
            importlib.import_module(f"oracles.{task_id}.{module}")
    cases = sorted(REGISTRY.get(task_id, []), key=lambda c: (c.level, _natural(c.id)))
    return Suite(task_id=task_id, cases=cases, root=root)


# ----------------------------------------------------------------------------- execução


def _pending_outcome(spec: CaseSpec) -> CaseOutcome:
    return CaseOutcome(case_id=spec.id, level=spec.level, outcome="PENDING", requirements=list(spec.requirements),
                       error=f"pendente: {spec.pending}")


def run_case(
    spec: CaseSpec, session: BrowserSession, url: str, viewport: tuple[int, int], block_network: bool = True,
    root_timeout_ms: int = ROOT_TIMEOUT_MS, mutation: Any | None = None, mutation_applied: list[bool] | None = None,
) -> CaseOutcome:
    """Executa um caso numa página nova (contexto isolado, relógio falso instalado ANTES do goto)."""
    if spec.pending:
        return _pending_outcome(spec)
    if spec.fn is None:
        raise ValueError(f"caso {spec.id} sem função")

    started = now_ms()
    parsed = urlparse(url)
    page_errors: list[str] = []
    blocked_urls: list[str] = []
    context = session.new_context(viewport)
    checks: Checks | None = None
    error: str | None = None
    blocked = crashed = False
    try:
        context.add_init_script(SPIES_JS)
        if mutation is not None and mutation.init_js:
            context.add_init_script(mutation.init_js)
        page = context.new_page()
        page.set_default_timeout(ACTION_TIMEOUT_MS)
        try:
            expect.set_options(timeout=EXPECT_TIMEOUT_MS)
        except AttributeError:  # pragma: no cover - versões antigas do Playwright
            pass
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        if spec.uses_clock:
            page.clock.install(time=spec.fixed_now or FIXED_NOW)
        if block_network:
            session.install_network_policy(context, f"{parsed.scheme}://{parsed.netloc}", blocked_urls)
        checks = Checks(page, page_errors)
        # a MESMA sequência do render inicial (goto -> app-root -> fonts.ready -> render_settle_ms): sem a espera de
        # assentamento, o primeiro caso de um Chromium recém-aberto podia começar antes do conteúdo montar
        load_error = load_app(page, url, session.render_settle_ms, root_timeout_ms, settle_if_failed=False)
        if load_error is not None:
            checks.ok("o app renderizou (app-root com conteúdo)", False, load_error)
            raise BlockedError("app-root não renderizou")
        if mutation is not None:
            applied = bool(page.evaluate(mutation.after_js)) if mutation.after_js else True
            if mutation_applied is not None:
                mutation_applied.append(applied)
        spec.fn(page, checks)
    except BlockedError:
        blocked = True
    except Exception as exc:  # noqa: BLE001 - exceção inesperada: o caso vira NO com o erro registrado
        crashed = True
        error = f"{type(exc).__name__}: {str(exc).strip().splitlines()[0] if str(exc).strip() else ''}"[:300]
    finally:
        context.close()

    records = checks.records if checks else []
    return CaseOutcome(
        case_id=spec.id, level=spec.level, outcome=classify(records, crashed=crashed, blocked=blocked),
        blocked=blocked, n_pass=sum(r.status == "pass" for r in records),
        n_total=sum(r.status in ("pass", "fail") for r in records), n_steps=sum(r.status == "step" for r in records),
        requirements=list(spec.requirements), failed=checks.failed() if checks else [],
        error=error, duration_ms=int(now_ms() - started),
    )


def run_suite(
    suite: Suite, session: BrowserSession, url: str, viewport: tuple[int, int],
    levels: tuple[str, ...] | list[str] = ("A", "B"), block_network: bool = True,
) -> list[CaseOutcome]:
    """Executa os casos dos níveis pedidos. Se o app não renderiza, só o primeiro caso espera os 10 s
    pelo `app-root`; os seguintes confirmam em 1,5 s (o resultado é o mesmo: NO bloqueado)."""
    outcomes: list[CaseOutcome] = []
    root_timeout = ROOT_TIMEOUT_MS
    for spec in suite.cases:
        if spec.level not in levels:
            continue
        outcome = run_case(spec, session, url, viewport, block_network, root_timeout_ms=root_timeout)
        if outcome.blocked and outcome.failed and outcome.failed[0].startswith("o app renderizou"):
            root_timeout = 1500
        outcomes.append(outcome)
    return outcomes


# ----------------------------------------------------------------------------- lint

_FORBIDDEN = [
    (re.compile(r"""locator\(\s*(?:f|r)?["']\s*[#.]"""), "seletor CSS por id/classe (use papel, rótulo ou texto visível)"),
    (re.compile(r"data-testid|get_by_test_id|\bdata-test\b"), "data-testid (só a spec revelaria o id)"),
    (re.compile(r"""\[(?:class|id)\s*[\^$*~|]?="""), "atributo class/id em seletor"),
    (re.compile(r"""locator\(\s*(?:f|r)?["']\s*css\s*="""), "css= explícito"),
]
_BODY_SCORES = re.compile(r"\bt\.(?:ok|eventually)\(")  # só ok/eventually pontuam; act e require são passos


def _strip_comment(line: str) -> str:
    """Remove o comentário `# ...` da linha, ignorando `#` dentro de aspas (ex.: `locator("#id")`)."""
    quote = ""
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "#":
            return line[:i]
    return line


def lint_suite(suite: Suite, oracles_dir: str | Path) -> list[str]:
    """Problemas de autoria da suíte (lista vazia = ok)."""
    oracles_dir = Path(oracles_dir)
    problems: list[str] = []
    ids = [c.id for c in suite.cases]
    problems += [f"id de caso repetido: {i}" for i in sorted({i for i in ids if ids.count(i) > 1})]

    try:
        requirements = {r.id: r for r in load_requirements(oracles_dir, suite.task_id)}
        pending = {p.id for p in load_pending(oracles_dir, suite.task_id)}
    except (OSError, ValueError) as exc:
        return [*problems, f"requirements/pending ilegíveis: {exc}"]

    for spec in suite.cases:
        if spec.level == "A" and not spec.requirements:
            problems.append(f"{spec.id}: caso de nível A sem requisitos (rastreabilidade)")
        unknown = [r for r in spec.requirements if r not in requirements]
        if unknown:
            problems.append(f"{spec.id}: requisitos inexistentes {unknown}")
        if spec.pending and spec.pending not in pending:
            problems.append(f"{spec.id}: pendência {spec.pending} não existe em pending.yaml")
        if not spec.pending and spec.fn is not None:
            body = inspect.getsource(spec.fn).split("\n", 2)[-1]
            if not _BODY_SCORES.search(body):
                problems.append(
                    f"{spec.id}: o caso não tem nenhuma asserção pontuada (t.ok/t.eventually); act e require são passos, "
                    "então ele daria NO por 'sem asserção pontuada'"
                )

    sources = sorted(suite.root.glob("*.py")) + sorted((oracles_dir / "common").glob("*.py"))
    for path in sources:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            code = _strip_comment(line)
            for pattern, message in _FORBIDDEN:
                if pattern.search(code):
                    problems.append(f"{path.relative_to(oracles_dir.parent).as_posix()}:{number}: {message}")
    return problems


# ----------------------------------------------------------------------------- rastreabilidade


def build_traceability(suite: Suite, requirements: list[Requirement]) -> tuple[str, list[str]]:
    """Matriz requisito × casos (markdown) e os problemas de cobertura.

    Um requisito de categoria `a` precisa de ao menos um caso de nível A NÃO pendente; `c` precisa
    declarar a pendência; `b` é medido pelas métricas visuais (sem caso); `s` é nível B.
    """
    by_req: dict[str, list[CaseSpec]] = {r.id: [] for r in requirements}
    for spec in suite.cases:
        for req in spec.requirements:
            by_req.setdefault(req, []).append(spec)

    problems: list[str] = []
    rows = []
    for req in requirements:
        cases = by_req[req.id]
        executed = [c for c in cases if not c.pending]
        level_a = [c for c in executed if c.level == "A"]
        level_b = [c for c in executed if c.level == "B"]
        if req.category == "b":
            status = "visual (Design2Code/VES)"
        elif req.category == "s":
            status = "nível B" if level_b else "sem caso"
            if not level_b:
                problems.append(f"{req.id}: requisito da spec sem caso de nível B")
        elif req.category == "c":
            status = ("parcial" if level_a else "pendente") + f" ({', '.join(req.pending)})"
            if not req.pending:
                problems.append(f"{req.id}: categoria c sem pendência declarada")
        else:
            status = "coberto" if level_a else "SEM CASO"
            if not level_a:
                problems.append(f"{req.id}: requisito testável sem caso de nível A executável")
        names = ", ".join(f"{c.id}{' (pendente)' if c.pending else ''}" for c in cases) or "—"
        text = req.text.replace("|", "\\|").replace("\n", " ")
        rows.append(f"| {req.id} | {text} | {req.category} | {req.info_source} | {names} | {status} |")

    known = set(by_req)
    problems += [f"caso {c.id} cita requisito inexistente {r}" for c in suite.cases for r in c.requirements
                 if r not in {x.id for x in requirements} and r in known]
    header = (
        f"# Rastreabilidade: {suite.task_id}\n\n_Gerado por `specui oracle-matrix`; não edite._\n\n"
        "| Requisito | Texto | Cat. | Fonte | Casos | Status |\n|---|---|---|---|---|---|\n"
    )
    return header + "\n".join(rows) + "\n", problems
