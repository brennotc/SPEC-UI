"""Proveniência e congelamento do oráculo.

Depois do piloto, o oráculo é CONGELADO com uma tag git (`oracle-v1`). Toda execução principal
grava com qual versão rodou; mexer em `oracles/` depois exige nova tag e reexecutar as 12 células.

- `tree_hash`: hash da ÁRVORE git de `oracles/` em HEAD (não quebra quando outros arquivos mudam,
  ao contrário de `git describe --exact-match`);
- `tag`: a tag `oracle-*` cuja árvore `T:oracles` é igual a `tree_hash`, e que bate com `VERSION`;
- `dirty`: há mudança não commitada em `oracles/`;
- `content_sha256`: hash do conteúdo (funciona fora do git);
- `pending_sha256`, `mention_patterns_sha256`: decidir uma pendência ou mudar um padrão de menção
  é mudar o instrumento: o hash entra no registro de cada execução.
"""

import hashlib
import subprocess
from pathlib import Path

import yaml
from pydantic import BaseModel

_HASHED_SUFFIXES = {".py", ".yaml", ".yml", ".md"}
_NOT_HASHED = {"CHANGELOG.md", "traceability.md"}  # documentação gerada/histórico: não muda o instrumento


class OracleProvenance(BaseModel):
    tag: str | None = None
    tree_hash: str | None = None
    dirty: bool = False
    content_sha256: str
    pending_sha256: str
    mention_patterns_sha256: str
    version_file: str | None = None  # conteúdo de oracles/VERSION


def _normalized(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


def _files(oracles_dir: Path, names: set[str] | None = None, suffixes: set[str] | None = None) -> list[Path]:
    out = []
    for path in sorted(oracles_dir.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.name in _NOT_HASHED:
            continue
        if suffixes is not None and path.suffix not in suffixes:
            continue
        if names is not None and path.name not in names:
            continue
        out.append(path)
    return out


def _hash(oracles_dir: Path, paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(oracles_dir).as_posix().encode("utf-8") + b"\0")
        digest.update(_normalized(path) + b"\0")
    return digest.hexdigest()


def content_sha256(oracles_dir: str | Path) -> str:
    """Hash dos .py/.yaml/.md de `oracles/` (fim de linha normalizado; sem caches nem docs geradas)."""
    root = Path(oracles_dir)
    return _hash(root, _files(root, suffixes=_HASHED_SUFFIXES))


def pending_sha256(oracles_dir: str | Path) -> str:
    root = Path(oracles_dir)
    return _hash(root, _files(root, names={"pending.yaml"}))


def mention_patterns_sha256(oracles_dir: str | Path) -> str:
    """Só os `mention_patterns` (id -> padrões), para detectar mudança mesmo em arquivo reformatado."""
    root = Path(oracles_dir)
    digest = hashlib.sha256()
    for path in _files(root, names={"requirements.yaml"}):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for req in data.get("requirements", []):
            digest.update(f"{path.parent.name}/{req['id']}:{'|'.join(req.get('mention_patterns', []))}\n".encode())
    return digest.hexdigest()


def _git(repo_root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(["git", "-C", str(repo_root), *args], capture_output=True, text=True, check=False)
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def read_provenance(repo_root: str | Path, oracles_dir: str | Path) -> OracleProvenance:
    repo_root, oracles_dir = Path(repo_root).resolve(), Path(oracles_dir).resolve()
    try:
        rel = oracles_dir.relative_to(repo_root).as_posix()
    except ValueError:  # oracles/ fora do repositório (testes): só os hashes de conteúdo existem
        rel = None
    tree = _git(repo_root, "rev-parse", f"HEAD:{rel}") if rel else None
    tag = None
    for candidate in ((_git(repo_root, "tag", "-l", "oracle-*") or "").splitlines() if rel else []):
        if tree and _git(repo_root, "rev-parse", f"{candidate}:{rel}") == tree:
            tag = candidate
    dirty = bool(_git(repo_root, "status", "--porcelain", "--", rel)) if rel else False
    version_path = oracles_dir / "VERSION"
    return OracleProvenance(
        tag=tag, tree_hash=tree, dirty=dirty,
        content_sha256=content_sha256(oracles_dir), pending_sha256=pending_sha256(oracles_dir),
        mention_patterns_sha256=mention_patterns_sha256(oracles_dir),
        version_file=version_path.read_text(encoding="utf-8").strip() if version_path.is_file() else None,
    )


def freeze_problems(prov: OracleProvenance) -> list[str]:
    """Motivos pelos quais uma execução PRINCIPAL deve ser recusada (vazio = pode rodar)."""
    problems = []
    if prov.dirty:
        problems.append("há mudanças não commitadas em oracles/ (o oráculo precisa estar congelado)")
    if prov.tag is None:
        problems.append("nenhuma tag oracle-* aponta para a versão atual de oracles/ (git tag oracle-v1)")
    elif prov.version_file != prov.tag:
        problems.append(f"oracles/VERSION ({prov.version_file!r}) difere da tag ({prov.tag!r})")
    return problems
