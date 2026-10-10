"""Oráculos funcionais: protocolo, execução, requisitos, proveniência e mutação."""

from specui.oracle.protocol import BlockedError, CaseSpec, Checks, case, classify
from specui.oracle.runner import (
    Suite,
    build_traceability,
    lint_suite,
    load_suite,
    run_case,
    run_suite,
)

__all__ = [
    "BlockedError", "CaseSpec", "Checks", "Suite", "build_traceability", "case", "classify",
    "lint_suite", "load_suite", "run_case", "run_suite",
]
