"""`specui export`: pacote OPCIONAL para depósito com DOI (results/ nunca vai para o git).

Conteúdo: record.json, prompts, resposta bruta, screenshot, arquivos gerados (sem `dist/` nem `node_modules/`), e
`aggregate/`; mais `MANIFEST.json` com o sha256 de cada arquivo. Não inclui `.env`, `private/` nem resultados do piloto.
"""

import hashlib
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

_RUN_FILES = ("record.json", "prompt.system.txt", "prompt.user.txt", "response.raw.txt", "screenshot.png",
              "dom_blocks.json", "pairs.json", "axe.json", "build.stdout.txt", "build.stderr.txt")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect(results_dir: Path) -> list[Path]:
    """Arquivos do pacote, relativos a `results_dir` (a pasta `pilot/` fica de fora)."""
    files: list[Path] = []
    runs = results_dir / "runs"
    for run_dir in sorted(runs.iterdir()) if runs.is_dir() else []:
        for name in _RUN_FILES:
            if (run_dir / name).is_file():
                files.append(run_dir / name)
        generated = run_dir / "generated"
        if generated.is_dir():
            files += [p for p in sorted(generated.rglob("*")) if p.is_file() and "node_modules" not in p.parts]
    for name in ("manifest.jsonl", "run_meta.json"):
        if (results_dir / name).is_file():
            files.append(results_dir / name)
    aggregate = results_dir / "aggregate"
    if aggregate.is_dir():
        files += [p for p in sorted(aggregate.rglob("*")) if p.is_file()]
    return files


def export_results(results_dir: str | Path, out: str | Path, extra: dict | None = None) -> Path:
    results_dir, out = Path(results_dir), Path(out)
    files = collect(results_dir)
    if not files:
        raise FileNotFoundError(f"nada para exportar em {results_dir}")
    out.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "n_files": len(files),
        "files": {p.relative_to(results_dir).as_posix(): _sha256(p) for p in files},
        **(extra or {}),
    }
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            zf.write(p, p.relative_to(results_dir).as_posix())
        zf.writestr("MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return out
