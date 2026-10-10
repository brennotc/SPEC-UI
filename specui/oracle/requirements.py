"""Requisitos (`requirements.yaml`) e decisões pendentes (`pending.yaml`) de cada tarefa.

Regras de decisão das pendências (o `## Prompt` NÃO muda, logo uma decisão não pode criar
requisito que o prompt não contém):

  1. o prompt admite mais de uma leitura   -> o teste de nível A aceita qualquer leitura consistente;
  2. o prompt não descreve o mecanismo     -> testa-se só o observável sem o mecanismo; o resto sai do
                                              nível A e é declarado "não testável a partir do prompt";
  3. exigência específica da spec          -> nível B.
"""

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator

Category = Literal["a", "b", "c", "s"]  # a: testável do prompt | b: só visual | c: ambíguo | s: só da spec
InfoSource = Literal["image", "behavior", "spec_only"]


class Requirement(BaseModel):
    id: str
    text: str  # citação do prompt (ou da spec, para category "s")
    category: Category
    info_source: InfoSource
    pending: list[str] = Field(default_factory=list)  # PD-* que bloqueiam o teste
    mention_patterns: list[str] = Field(default_factory=list)  # regex de menção em prompts livres

    @field_validator("mention_patterns")
    @classmethod
    def _compile(cls, patterns: list[str]) -> list[str]:
        for pattern in patterns:
            try:
                re.compile(pattern)  # regex inválida falha na carga, não no meio da análise
            except re.error as exc:
                raise ValueError(f"mention_pattern inválido {pattern!r}: {exc}") from exc
        return patterns


class PendingDecision(BaseModel):
    id: str
    question: str
    rule: Literal[1, 2, 3]
    options: list[str] = Field(default_factory=list)
    status: Literal["open", "decided"] = "open"
    decision: str | None = None
    decided_on: str | None = None
    blocks: list[str] = Field(default_factory=list)  # casos/asserções afetados


def _read(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_requirements(oracles_dir: str | Path, task_id: str) -> list[Requirement]:
    path = Path(oracles_dir) / task_id / "requirements.yaml"
    reqs = [Requirement.model_validate(r) for r in _read(path).get("requirements", [])]
    ids = [r.id for r in reqs]
    if len(set(ids)) != len(ids):
        raise ValueError(f"{path}: ids de requisito repetidos")
    return reqs


def load_pending(oracles_dir: str | Path, task_id: str) -> list[PendingDecision]:
    path = Path(oracles_dir) / task_id / "pending.yaml"
    if not path.is_file():
        return []
    return [PendingDecision.model_validate(p) for p in _read(path).get("pending", [])]
