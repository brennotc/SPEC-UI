"""Carga da configuração do experimento (YAML versionado) e dos segredos (.env)."""

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from specui.models import RunConfig

_ENV_LOADED = False


def find_repo_root(start: Path | None = None) -> Path:
    """Sobe a partir de `start` até achar a raiz do repositório (pyproject.toml)."""
    here = (start or Path(__file__).resolve()).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise FileNotFoundError(f"raiz do repositório (pyproject.toml) não encontrada a partir de {here}")


def load_env(repo_root: Path) -> None:
    """Carrega o .env uma única vez (só segredos). Não sobrescreve variáveis já definidas."""
    global _ENV_LOADED
    if not _ENV_LOADED:
        load_dotenv(repo_root / ".env", override=False)
        _ENV_LOADED = True


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Mescla dicts recursivamente; listas e escalares do `override` substituem os do `base`."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _read_yaml(path: Path, _seen: tuple[Path, ...] = ()) -> dict[str, Any]:
    """Lê um YAML resolvendo `extends: outro.yaml` (relativo ao arquivo), com detecção de ciclo."""
    path = path.resolve()
    if path in _seen:
        chain = " -> ".join(p.name for p in (*_seen, path))
        raise ValueError(f"ciclo em extends: {chain}")
    if not path.is_file():
        raise FileNotFoundError(f"configuração não encontrada: {path}")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise TypeError(f"{path}: o YAML deve ser um mapeamento")
    parent = data.pop("extends", None)
    if parent is None:
        return data
    base = _read_yaml(path.parent / str(parent), (*_seen, path))
    return _deep_merge(base, data)


def load_config(
    path: str | Path,
    overrides: dict[str, Any] | None = None,
    repo_root: str | Path | None = None,
) -> RunConfig:
    """Carrega e valida uma configuração.

    `overrides` é mesclado por cima do YAML (mesma regra do `extends`). `repo_root` padrão é a
    pasta que contém o pyproject.toml.
    """
    path = Path(path)
    root = Path(repo_root).resolve() if repo_root else find_repo_root(path.resolve())
    load_env(root)
    data = _read_yaml(path)
    if overrides:
        data = _deep_merge(data, overrides)
    data["repo_root"] = str(root)
    return RunConfig.model_validate(data)


def config_sha256(cfg: RunConfig) -> str:
    """Hash estável da configuração (ignora o caminho absoluto do repositório)."""
    payload = cfg.model_dump(mode="json", exclude={"repo_root"})
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
