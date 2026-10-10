"""Snapshot CURADO do piloto (results/pilot/ fica fora do git): copia só a evidência que justifica o CHANGELOG do oráculo.

Por run do gerador real (última tentativa de cada célula): `record.json`, `screenshot.png` e `response.raw.txt`.
Na raiz: failure_report.{md,csv}, sensitivity.csv, sensitivity_baseline.csv e manifest.jsonl SEM as linhas do mock.
NUNCA copia dist/ (≈ 6,6 MB por run), generated/ (está em response.raw.txt), css_snapshot, axe, dom_blocks, build.*, prompt.* nem o run mock.

    python scripts/snapshot_pilot.py --out docs/pilot-1
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

PER_RUN = ("record.json", "screenshot.png", "response.raw.txt")
ROOT_FILES = ("failure_report.md", "failure_report.csv", "sensitivity.csv", "sensitivity_baseline.csv")
FORBIDDEN_PARTS = {"dist", "generated", "node_modules"}


def snapshot(results_pilot: Path, out: Path) -> list[Path]:
    """Copia a evidência curada e devolve os arquivos escritos (relativos a `out`)."""
    manifest = (results_pilot / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    entries = [json.loads(line) for line in manifest if line.strip()]
    latest: dict[str, dict] = {}
    for entry in entries:
        latest[entry["cell_key"]] = entry
    real = {k: e for k, e in latest.items() if "|mock:" not in k}

    written: list[Path] = []

    def put(src: Path, dst: Path) -> None:
        if FORBIDDEN_PARTS & set(src.parts):
            raise ValueError(f"o snapshot nunca inclui {src}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        written.append(dst.relative_to(out))

    for entry in sorted(real.values(), key=lambda e: e["cell_key"]):
        run_dir = results_pilot / "runs" / entry["run_id"]
        for name in PER_RUN:
            if (run_dir / name).is_file():
                put(run_dir / name, out / "runs" / entry["run_id"] / name)
    for name in ROOT_FILES:
        if (results_pilot / name).is_file():
            put(results_pilot / name, out / name)

    keep = {e["run_id"] for e in real.values()}
    kept_lines = [json.dumps(e, ensure_ascii=False) for e in entries if "|mock:" not in e["cell_key"]]
    (out / "manifest.jsonl").write_text("\n".join(kept_lines) + "\n", encoding="utf-8", newline="\n")
    written.append(Path("manifest.jsonl"))
    assert keep  # há ao menos um run real
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results", type=Path, default=REPO / "results" / "pilot")
    parser.add_argument("--out", type=Path, default=REPO / "docs" / "pilot-1")
    args = parser.parse_args()
    written = snapshot(args.results, args.out)
    print(f"{len(written)} arquivos em {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
