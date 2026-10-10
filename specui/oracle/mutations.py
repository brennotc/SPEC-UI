"""Sensibilidade do oráculo por MUTAÇÃO em tempo de execução.

Pega saídas reais do piloto em que um caso deu YES, estraga o app de um jeito conhecido (sem tocar no
código gerado) e confirma que o caso deixa de dar YES. Um teste que não percebe o app quebrado não mede nada.

Verdicts por (mutação, caso):
  KILLED       o caso era YES e agora é NO
  WEAK         o caso era YES e agora é PARTIAL (percebe só parte da quebra)
  SURVIVED     o caso continua YES com o app quebrado: o teste não mede o que diz medir
  NOT_APPLIED  a mutação não pôde ser aplicada (elemento inexistente) ou o caso não era YES antes
"""

import csv
import json
import shutil
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from specui.harness.browser import BrowserSession
from specui.harness.server import StaticServer
from specui.models import CaseOutcome
from specui.oracle.protocol import CaseSpec
from specui.oracle.runner import Suite, run_case

Verdict = str


@dataclass(frozen=True)
class Mutation:
    id: str
    operator: str
    description: str
    targets: tuple[str, ...]  # casos que DEVEM perceber a quebra
    init_js: str | None = None  # antes do app (init script)
    after_js: str | None = None  # depois do 1º render; devolve true se alterou algo
    replace: tuple[str, str] | None = None  # troca de texto nos bundles de dist/ (mutação de "fonte")


# ----------------------------------------------------------------------------- operadores


def _js(value: str) -> str:
    """Literal de string JavaScript."""
    return json.dumps(value, ensure_ascii=False)


def remove_all(mutation_id: str, selector: str, targets: Sequence[str]) -> Mutation:
    return Mutation(
        mutation_id, "remove_element", f"remove todos os '{selector}' da página", tuple(targets),
        after_js=f"() => {{ const n = document.querySelectorAll({_js(selector)}); n.forEach((e) => e.remove()); return n.length > 0; }}",
    )


def block_events(mutation_id: str, operator: str, types: Sequence[str], targets: Sequence[str]) -> Mutation:
    listed = ", ".join(_js(t) for t in types)
    return Mutation(
        mutation_id, operator, f"engole os eventos {', '.join(types)} antes de chegarem ao app", tuple(targets),
        init_js=f"[{listed}].forEach((type) => window.addEventListener(type, (e) => {{ e.stopImmediatePropagation(); e.preventDefault(); }}, true));",
    )


def change_text(mutation_id: str, old: str, new: str, targets: Sequence[str]) -> Mutation:
    return Mutation(
        mutation_id, "change_text", f"troca o texto '{old}' por '{new}'", tuple(targets),
        after_js=(
            f"() => {{ let changed = false; const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);"
            f" for (let n = w.nextNode(); n; n = w.nextNode()) if (n.nodeValue.includes({_js(old)})) {{ n.nodeValue = n.nodeValue.split({_js(old)}).join({_js(new)}); changed = true; }}"
            f" return changed; }}"
        ),
    )


def freeze_timers(mutation_id: str, targets: Sequence[str]) -> Mutation:
    return Mutation(
        mutation_id, "freeze_timer", "setInterval/setTimeout passam a não disparar nunca (o relógio do app para)", tuple(targets),
        after_js="() => { window.setInterval = () => 0; window.setTimeout = () => 0; window.requestAnimationFrame = () => 0; return true; }",
    )


def make_readonly(mutation_id: str, targets: Sequence[str]) -> Mutation:
    """Inputs, selects e textareas ficam somente leitura e desabilitados, INCLUSIVE os que surgem depois (ex.: o campo
    do card de criação do Kanban só aparece após o clique no +): um MutationObserver trava cada campo novo."""
    lock = "(e) => { e.readOnly = true; e.disabled = true; }"
    return Mutation(
        mutation_id, "make_readonly", "inputs, selects e textareas (atuais e futuros) ficam somente leitura e desabilitados",
        tuple(targets),
        after_js=(
            "() => { const sel = 'input, select, textarea'; const lock = " + lock + ";"
            " document.querySelectorAll(sel).forEach(lock);"
            " new MutationObserver(() => document.querySelectorAll(sel).forEach(lock))"
            ".observe(document.body, { childList: true, subtree: true }); return true; }"
        ),
    )


def neutralize_filters(mutation_id: str, targets: Sequence[str]) -> Mutation:
    """Faz os controles de FILTRO (input/select na faixa logo abaixo do header) pararem de reagir, sem tocar no resto.

    Diferente de `make_readonly`/`block_input_events`, que também derrubam o formulário de criação (e o caso morre na
    pré-condição, antes de exercitar o filtro): aqui as tarefas são criadas normalmente e só a filtragem fica inerte.
    A faixa é a do filtro no layout do prompt: abaixo do header (top > 50 px) e acima de 30 % da altura da janela."""
    js = (
        "() => { const inBand = (el) => { const r = el.getBoundingClientRect();"
        " return r.height > 0 && r.top > 50 && r.top < 0.3 * window.innerHeight; };"
        " const found = Array.from(document.querySelectorAll('input, select')).filter(inBand).length > 0;"
        " ['change', 'input', 'keyup', 'keydown', 'blur', 'focusout'].forEach((type) =>"
        " window.addEventListener(type, (e) => { if (e.target && e.target.getBoundingClientRect && inBand(e.target))"
        " e.stopImmediatePropagation(); }, true));"
        " return found; }"
    )
    return Mutation(
        mutation_id, "neutralize_filters", "os controles de filtro (faixa abaixo do header) deixam de reagir; o formulário do rodapé segue funcionando",
        tuple(targets), after_js=js,
    )


def unclamp_overflow(mutation_id: str, targets: Sequence[str]) -> Mutation:
    return Mutation(
        mutation_id, "unclamp_overflow", "remove a rolagem interna: overflow visível e altura automática em tudo", tuple(targets),
        after_js="() => { const s = document.createElement('style'); s.textContent = '* { overflow: visible !important; max-height: none !important; height: auto !important; }'; document.head.appendChild(s); return true; }",
    )


def text_replace(mutation_id: str, old: str, new: str, targets: Sequence[str]) -> Mutation:
    return Mutation(
        mutation_id, "source.text_replace", f"troca '{old}' por '{new}' nos bundles de dist/", tuple(targets), replace=(old, new),
    )


# ----------------------------------------------------------------------------- catálogo

CATALOG: dict[str, list[Mutation]] = {
    "easy_pomodoro": [
        freeze_timers("MUT-E1", ["E-A-05", "E-A-06", "E-A-09"]),
        block_events("MUT-E2", "block_click", ["click"], ["E-A-05", "E-A-06"]),
        remove_all("MUT-E3", "button", ["E-A-05", "E-A-06"]),
        make_readonly("MUT-E4", ["E-A-08", "E-A-09"]),
        change_text("MUT-E5", "Pomodoro", "Pomodor0", ["E-A-02"]),
        change_text("MUT-E6", "25:00", "99:99", ["E-A-01"]),
    ],
    "medium_tarefas": [
        block_events("MUT-M1", "block_click", ["click"], ["M-A-04", "M-A-07", "M-A-08"]),
        make_readonly("MUT-M2", ["M-A-04", "M-A-10", "M-A-11"]),
        block_events("MUT-M3", "block_input_events", ["input", "change"], ["M-A-04", "M-A-10"]),
        remove_all("MUT-M4", "button", ["M-A-04", "M-A-08"]),
        unclamp_overflow("MUT-M5", ["M-A-09"]),
        change_text("MUT-M6", "Hoje", "Today", ["M-A-05"]),
        change_text("MUT-M7", "Tarefas Para Fazer", "To do", ["M-A-01"]),
        neutralize_filters("MUT-M8", ["M-A-10", "M-A-11"]),  # exercita a filtragem em si, não a criação de tarefas
    ],
    "hard_kanban": [
        block_events("MUT-H1", "block_click", ["click"], ["H-A-05", "H-A-06", "H-A-07", "H-A-09"]),
        block_events("MUT-H2", "break_dnd", ["dragstart", "pointerdown", "mousedown"], ["H-A-11", "H-A-13", "H-A-14"]),
        make_readonly("MUT-H3", ["H-A-06"]),
        change_text("MUT-H4", "Em Progresso", "In Progress", ["H-A-02", "H-A-03"]),
        change_text("MUT-H5", "Kanban", "Quadro", ["H-A-01"]),
    ],
}


# ----------------------------------------------------------------------------- execução


@dataclass
class MutationRow:
    run_id: str
    task_id: str
    mutation_id: str
    operator: str
    case_id: str
    baseline: str | None
    mutated: str | None
    verdict: Verdict
    detail: str = ""
    extra: dict[str, str] = field(default_factory=dict)


@dataclass
class BaselineRow:
    """O que o caso fez no app INTACTO, com o mesmo detalhe do `failure_report` (para explicar todo NOT_APPLIED)."""

    run_id: str
    task_id: str
    case_id: str
    outcome: str
    blocked: bool
    n_pass: int
    n_total: int
    n_steps: int
    failed_assertions: str  # "<asserção> :: <detalhe>" separadas por " | ", como o failure_report
    error: str
    duration_ms: int


def baseline_row(run_id: str, task_id: str, outcome: CaseOutcome) -> BaselineRow:
    return BaselineRow(
        run_id, task_id, outcome.case_id, outcome.outcome, outcome.blocked, outcome.n_pass, outcome.n_total, outcome.n_steps,
        " | ".join(outcome.failed), outcome.error or "", outcome.duration_ms,
    )


def _diagnosis(b: BaselineRow) -> str:
    parts = [f"outcome={b.outcome}", f"blocked={b.blocked}"]
    if b.failed_assertions:
        parts.append(f"failed={b.failed_assertions}")
    if b.error:
        parts.append(f"error={b.error}")
    return "o caso não era YES no baseline (" + "; ".join(parts) + ")"


def verdict_for(baseline: str | None, mutated: str | None, applied: bool) -> Verdict:
    if baseline != "YES" or not applied or mutated is None:
        return "NOT_APPLIED"
    if mutated == "NO":
        return "KILLED"
    if mutated == "PARTIAL":
        return "WEAK"
    return "SURVIVED"


def _replaced_copy(dist: Path, old: str, new: str, workdir: Path) -> tuple[Path, bool]:
    target = workdir / "dist"
    shutil.copytree(dist, target)
    changed = False
    for path in target.rglob("*"):
        if path.is_file() and path.suffix in {".js", ".html", ".css", ".mjs"}:
            text = path.read_text(encoding="utf-8", errors="ignore")
            if old in text:
                path.write_text(text.replace(old, new), encoding="utf-8", newline="")
                changed = True
    return target, changed


def run_mutations(
    suite: Suite, session: BrowserSession, dist_dir: str | Path, viewport: tuple[int, int], run_id: str,
    catalog: Sequence[Mutation] | None = None, block_network: bool = True,
) -> list[MutationRow]:
    """Aplica cada mutação do catálogo da tarefa e compara cada caso-alvo com o baseline (app intacto)."""
    return run_mutations_with_baseline(suite, session, dist_dir, viewport, run_id, catalog, block_network)[0]


def run_mutations_with_baseline(
    suite: Suite, session: BrowserSession, dist_dir: str | Path, viewport: tuple[int, int], run_id: str,
    catalog: Sequence[Mutation] | None = None, block_network: bool = True,
) -> tuple[list[MutationRow], list[BaselineRow]]:
    """Como `run_mutations`, e devolve também o baseline detalhado de cada caso-alvo (outcome, bloqueio, asserções que
    falharam, erro): um NOT_APPLIED nunca fica sem diagnóstico."""
    mutations = list(catalog if catalog is not None else CATALOG.get(suite.task_id, []))
    cases: dict[str, CaseSpec] = {c.id: c for c in suite.cases}
    wanted = {cid for m in mutations for cid in m.targets if cid in cases}
    rows: list[MutationRow] = []
    dist_dir = Path(dist_dir)

    with StaticServer(dist_dir) as server:
        outcomes = {cid: run_case(cases[cid], session, server.url, viewport, block_network) for cid in sorted(wanted)}
    baseline_rows = [baseline_row(run_id, suite.task_id, o) for o in outcomes.values()]
    by_case = {b.case_id: b for b in baseline_rows}
    baseline = {cid: o.outcome for cid, o in outcomes.items()}

    for mutation in mutations:
        targets = [cid for cid in mutation.targets if cid in cases]
        with tempfile.TemporaryDirectory(prefix="specui-mut-") as tmp:
            served, replaced = dist_dir, True
            if mutation.replace is not None:
                served, replaced = _replaced_copy(dist_dir, *mutation.replace, Path(tmp))
            with StaticServer(served) as server:
                for case_id in targets:
                    if baseline.get(case_id) != "YES":
                        rows.append(MutationRow(run_id, suite.task_id, mutation.id, mutation.operator, case_id,
                                                baseline.get(case_id), None, "NOT_APPLIED", _diagnosis(by_case[case_id])))
                        continue
                    applied: list[bool] = []
                    outcome = run_case(cases[case_id], session, server.url, viewport, block_network,
                                       mutation=mutation, mutation_applied=applied)
                    was_applied = replaced and (bool(applied and applied[0]) if mutation.replace is None else True)
                    rows.append(MutationRow(
                        run_id, suite.task_id, mutation.id, mutation.operator, case_id, "YES", outcome.outcome,
                        verdict_for("YES", outcome.outcome, was_applied),
                        "" if was_applied else "a mutação não encontrou o que alterar",
                    ))
    return rows, baseline_rows


def write_sensitivity(rows: Sequence[MutationRow], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["run_id", "task_id", "mutation_id", "operator", "case_id", "baseline", "mutated", "verdict", "detail"]
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: getattr(row, k) for k in fields})
    return path


def write_baseline(rows: Sequence[BaselineRow], path: str | Path) -> Path:
    """`sensitivity_baseline.csv`: o baseline de cada caso-alvo em cada run, ao lado do `sensitivity.csv`."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["run_id", "task_id", "case_id", "outcome", "blocked", "n_pass", "n_total", "n_steps", "failed_assertions",
              "error", "duration_ms"]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, delimiter=";")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: getattr(row, k) for k in fields})
    return path


def summarize(rows: Sequence[MutationRow]) -> dict[str, dict[str, int]]:
    """Contagem de veredictos por caso (um caso que sobrevive a uma mutação-alvo precisa ser revisto)."""
    out: dict[str, dict[str, int]] = {}
    for row in rows:
        out.setdefault(row.case_id, {}).setdefault(row.verdict, 0)
        out[row.case_id][row.verdict] += 1
    return out
