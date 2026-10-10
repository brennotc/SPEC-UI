"""Nota funcional (WebGen-Bench): Accuracy = (N_yes + 0,5·N_partial) / N_total.

Só entram casos executados (YES, PARTIAL, NO). Casos PENDING (decisão do pesquisador aberta)
ficam fora do denominador. Um NO bloqueado (pré-condição que falhou) conta 0 e permanece no
denominador. A nota é por nível: A (derivado só do `## Prompt`; a nota PRINCIPAL) e B (exigências
específicas da spec; diagnóstica).

`accuracy_a_restricted` considera só os casos cujos requisitos podem ser inferidos do material que
o participante viu (`material_shown`), para prompts livres. Sem `material_shown` (no_spec e
with_spec) é igual a `accuracy_a`.
"""

from collections.abc import Iterable, Mapping

from specui.models import CaseOutcome, FunctionalMetrics, MaterialShown
from specui.oracle.requirements import Requirement

_POINTS = {"YES": 1.0, "PARTIAL": 0.5, "NO": 0.0}

# Que `info_source` cada material permite inferir.
COMPATIBLE_SOURCES: dict[str, frozenset[str]] = {
    "image": frozenset({"image"}),
    "image+brief": frozenset({"image", "behavior"}),
    "image+prototype": frozenset({"image", "behavior"}),
}


def accuracy(outcomes: Iterable[CaseOutcome], level: str | None = None) -> float | None:
    """(YES + 0,5·PARTIAL) / casos executados; None se nenhum caso foi executado."""
    scored = [o for o in outcomes if o.outcome in _POINTS and (level is None or o.level == level)]
    if not scored:
        return None
    return sum(_POINTS[o.outcome] for o in scored) / len(scored)


def compatible(case_requirements: Iterable[str], requirements: Mapping[str, Requirement],
               material_shown: MaterialShown | None) -> bool:
    """O caso só é justo para o participante se TODOS os seus requisitos eram inferíveis do material."""
    if material_shown is None:
        return True
    allowed = COMPATIBLE_SOURCES[material_shown]
    return all(requirements[r].info_source in allowed for r in case_requirements if r in requirements)


def accuracy_restricted(
    outcomes: Iterable[CaseOutcome], requirements: Mapping[str, Requirement],
    material_shown: MaterialShown | None, level: str = "A",
) -> float | None:
    selected = [o for o in outcomes if compatible(o.requirements, requirements, material_shown)]
    return accuracy(selected, level)


def compute_functional(
    outcomes: list[CaseOutcome], requirements: Mapping[str, Requirement] | None = None,
    material_shown: MaterialShown | None = None, suite_sha256: str | None = None,
    suite_git_tag: str | None = None,
) -> FunctionalMetrics:
    return FunctionalMetrics(
        accuracy_a=accuracy(outcomes, "A"),
        accuracy_a_restricted=accuracy_restricted(outcomes, requirements or {}, material_shown, "A"),
        accuracy_b=accuracy(outcomes, "B"),
        cases=outcomes, suite_sha256=suite_sha256, suite_git_tag=suite_git_tag,
    )
