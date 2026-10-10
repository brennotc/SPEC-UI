"""Fixtures compartilhadas."""

from pathlib import Path

import pytest

from specui.models import ScaffoldInfo
from specui.tasks import load_tasks

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def tasks():
    """As 3 tarefas reais do repositório."""
    return load_tasks(REPO_ROOT / "benchmarks")


@pytest.fixture(scope="session")
def scaffold() -> ScaffoldInfo:
    """Scaffold fictício: o real só existe na Fase 3."""
    return ScaffoldInfo(
        version="test",
        lock_sha256="0" * 64,
        angular_version="20.0.0",
        packages={
            "@angular/core": "20.0.0",
            "tailwindcss": "4.1.0",
            "@ng-icons/core": "31.0.0",
            "@ng-icons/heroicons": "31.0.0",
            "@ng-icons/lucide": "31.0.0",
            "@fontsource/inter": "5.2.0",
        },
    )
