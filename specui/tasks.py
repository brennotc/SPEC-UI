"""Carga das tarefas de benchmarks/tasks/<nivel>/<id>.md (+ <id>.png)."""

import hashlib
import re
import struct
import warnings
from pathlib import Path

import yaml

from specui.models import DIFFICULTIES, Task

_PROMPT_HEADING = re.compile(r"^## Prompt[ \t]*$", re.MULTILINE)
_SPEC_HEADING = re.compile(r"^## Specification[ \t]*$", re.MULTILINE)
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def png_size(path: Path) -> tuple[int, int]:
    """Largura x altura lidas do cabeçalho IHDR do PNG (sem depender do Pillow)."""
    with open(path, "rb") as f:
        head = f.read(24)
    if len(head) < 24 or head[:8] != _PNG_SIGNATURE or head[12:16] != b"IHDR":
        raise ValueError(f"{path}: não é um PNG válido")
    width, height = struct.unpack(">II", head[16:24])
    return int(width), int(height)


def _parse_frontmatter(block: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in block.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        result[key.strip()] = value.strip()
    return result


def split_sections(markdown: str) -> tuple[dict[str, str], str, str]:
    """Separa (frontmatter, texto de '## Prompt', texto de '## Specification').

    O texto de cada seção NÃO inclui o cabeçalho nem o frontmatter. Fins de linha são
    normalizados para LF.
    """
    text = markdown.replace("\r\n", "\n").replace("\r", "\n")
    frontmatter: dict[str, str] = {}
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end == -1:
            raise ValueError("frontmatter sem fechamento '---'")
        frontmatter = _parse_frontmatter(text[4:end])
        text = text[end + len("\n---"):].lstrip("\n")

    prompt_match = _PROMPT_HEADING.search(text)
    spec_match = _SPEC_HEADING.search(text)
    if not prompt_match:
        raise ValueError("seção '## Prompt' não encontrada")
    if not spec_match:
        raise ValueError("seção '## Specification' não encontrada")
    if spec_match.start() < prompt_match.start():
        raise ValueError("'## Specification' aparece antes de '## Prompt'")

    prompt_text = text[prompt_match.end():spec_match.start()].strip()
    spec_text = text[spec_match.end():].strip()
    if not prompt_text:
        raise ValueError("seção '## Prompt' vazia")
    if not spec_text:
        raise ValueError("seção '## Specification' vazia")
    return frontmatter, prompt_text, spec_text


def load_figma_frames(tasks_dir: Path) -> dict[str, dict]:
    """Lê benchmarks/tasks/figma_frames.yaml (tarefa -> node_id/png)."""
    path = tasks_dir / "figma_frames.yaml"
    if not path.is_file():
        return {}
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return dict(data.get("frames") or {})


def load_tasks(benchmarks_dir: str | Path, select: list[str] | None = None) -> list[Task]:
    """Carrega as tarefas de <benchmarks_dir>/tasks/{easy,medium,hard}/*.md.

    A dificuldade vem da pasta (cruzada com `complexity` do frontmatter). `select` filtra por
    dificuldade ("easy") ou por id ("easy_pomodoro"). Falha com erro claro se faltar o PNG.
    """
    tasks_dir = Path(benchmarks_dir) / "tasks"
    if not tasks_dir.is_dir():
        raise FileNotFoundError(f"pasta de tarefas não encontrada: {tasks_dir}")
    frames = load_figma_frames(tasks_dir)

    tasks: list[Task] = []
    for difficulty in DIFFICULTIES:
        for md_path in sorted((tasks_dir / difficulty).glob("*.md")):
            if md_path.name.startswith("_template"):
                continue
            task_id = md_path.stem
            frontmatter, prompt_text, spec_text = split_sections(
                md_path.read_text(encoding="utf-8")
            )
            declared_id = frontmatter.get("id")
            if declared_id and declared_id != task_id:
                raise ValueError(
                    f"{md_path.name}: id do frontmatter ('{declared_id}') difere do nome do arquivo"
                )
            declared_level = frontmatter.get("complexity", "").lower()
            if declared_level and declared_level != difficulty:
                warnings.warn(
                    f"{md_path.name}: complexity '{declared_level}' difere da pasta '{difficulty}'; "
                    "vale a pasta",
                    stacklevel=2,
                )

            png_path = md_path.with_suffix(".png")
            if not png_path.is_file():
                raise FileNotFoundError(
                    f"tarefa '{task_id}': PNG de referência não encontrado em {png_path} "
                    "(o PNG exportado do Figma é obrigatório)"
                )
            node_id = (frames.get(task_id) or {}).get("node_id")
            if node_id in (None, "", "TODO"):
                node_id = None

            tasks.append(
                Task(
                    id=task_id,
                    difficulty=difficulty,
                    md_path=str(md_path),
                    prompt_text=prompt_text,
                    spec_text=spec_text,
                    image_path=str(png_path),
                    image_size=png_size(png_path),
                    image_sha256=sha256_bytes(png_path.read_bytes()),
                    figma_node_id=node_id,
                )
            )

    unknown_frames = set(frames) - {t.id for t in tasks}
    if unknown_frames:
        warnings.warn(
            f"figma_frames.yaml cita tarefas inexistentes: {sorted(unknown_frames)}", stacklevel=2
        )
    if select:
        wanted = set(select)
        known = {t.id for t in tasks} | set(DIFFICULTIES)
        missing = wanted - known
        if missing:
            raise ValueError(f"tarefas desconhecidas em select: {sorted(missing)}")
        tasks = [t for t in tasks if t.id in wanted or t.difficulty in wanted]
    if not tasks:
        raise FileNotFoundError(f"nenhuma tarefa encontrada em {tasks_dir}")
    return tasks
