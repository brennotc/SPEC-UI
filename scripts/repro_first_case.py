"""Reprodução da corrida do PRIMEIRO caso após abrir o Chromium (piloto 1, mutação de E-A-01).

A cada rodada: lança um Chromium NOVO (processo novo, como o `specui mutate` faz uma vez), roda UM caso contra o dist de um
run do piloto, fecha o navegador e registra outcome, bloqueio, asserções falhas e erro. Só leitura: não grava em results/.

    python scripts/repro_first_case.py --task easy_pomodoro --run easy_pomodoro-no_spec__text --case E-A-01 --n 20 \
        --out docs/pilot-1/corrida-E-A-01-antes.txt
"""

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from specui.config import load_config  # noqa: E402
from specui.harness import BrowserSession, StaticServer  # noqa: E402
from specui.oracle import load_suite  # noqa: E402
from specui.oracle.runner import run_case  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--task", required=True)
    parser.add_argument("--run", required=True, help="trecho do nome do run do piloto (google, com dist/)")
    parser.add_argument("--case", required=True)
    parser.add_argument("--n", type=int, default=20)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    cfg = load_config(REPO / "configs" / "pilot.yaml")
    runs = sorted(p for p in (cfg.path("results_dir") / "pilot" / "runs").iterdir()
                  if args.run in p.name and "__google__" in p.name and (p / "dist").is_dir())
    if len(runs) != 1:
        print(f"esperava 1 run para '{args.run}', achei {len(runs)}: {[p.name for p in runs]}", file=sys.stderr)
        return 2
    run = runs[0]
    spec = next(c for c in load_suite(cfg.path("oracles_dir"), args.task).cases if c.id == args.case)

    lines = [f"run: {run.name}", f"caso: {args.case} ({args.task})", f"rodadas: {args.n}, um Chromium novo por rodada", ""]
    tally: Counter[str] = Counter()
    for i in range(1, args.n + 1):
        started = time.monotonic()
        with StaticServer(run / "dist") as server, BrowserSession(cfg.clock_epoch_iso, cfg.render_settle_ms, cfg.block_network) as session:
            outcome = run_case(spec, session, server.url, cfg.viewport or (1440, 900), cfg.block_network)
        tally[outcome.outcome] += 1
        lines.append(
            f"{i:02d}  {outcome.outcome:7s} blocked={outcome.blocked!s:5s} pass={outcome.n_pass}/{outcome.n_total} steps={outcome.n_steps} "
            f"{time.monotonic() - started:5.1f}s  failed={outcome.failed}  error={outcome.error}"
        )
        print(lines[-1], flush=True)
    lines += ["", f"resumo: {dict(tally)}"]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
