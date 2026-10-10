"""Relatório de falhas do piloto: o insumo da classificação que decide o que pode mudar no oráculo.

Para cada execução do piloto: status, taxas por modelo (formato, contrato, build, truncamento, recusa) e, para cada caso
do oráculo que NÃO deu YES, as asserções que falharam. A coluna `classification` fica em branco para o pesquisador:

  test_defect   o app fez o que o prompt pede e o teste errou            -> corrige o teste (CHANGELOG)
  adapter_gap   o app fez certo, mas de um jeito que o adaptador não acha -> corrige o adaptador (CHANGELOG)
  model_defect  o app não fez o que o prompt pede                         -> NÃO mexe: é resultado
  ambiguity     o prompt admite a leitura do app e o teste não aceita     -> decisão em pending.yaml (regra 1/2)
"""

import csv
from collections import Counter
from pathlib import Path

from specui.models import RunRecord
from specui.storage import RunStore

CLASSES = ("test_defect", "adapter_gap", "model_defect", "ambiguity")
_FIELDS = ["run_id", "task_id", "prompt_kind", "modality", "model", "status", "case_id", "level", "outcome",
           "blocked", "failed_assertions", "error", "classification", "note"]


def _rate(values: list[bool]) -> str:
    return f"{sum(values)}/{len(values)}" if values else "—"


def failure_rows(records: list[RunRecord]) -> list[dict[str, str]]:
    rows = []
    for rec in records:
        base = {"run_id": rec.run_id, "task_id": rec.task_id, "prompt_kind": rec.prompt_kind, "modality": rec.modality,
                "model": f"{rec.provider}:{rec.model_id_requested}", "status": rec.status}
        if rec.status != "done" or rec.functional is None:
            rows.append(base | {"case_id": "—", "level": "—", "outcome": "—", "blocked": "",
                                "failed_assertions": "", "error": "; ".join(rec.errors)[:500], "classification": "", "note": ""})
            continue
        for case in rec.functional.cases:
            if case.outcome in ("YES", "PENDING"):
                continue
            rows.append(base | {
                "case_id": case.case_id, "level": case.level, "outcome": case.outcome, "blocked": "sim" if case.blocked else "",
                "failed_assertions": " | ".join(case.failed), "error": case.error or "", "classification": "", "note": "",
            })
    return rows


def write_pilot_report(results_dir: str | Path) -> dict[str, Path]:
    store = RunStore(results_dir, "pilot")
    records = [r for r in store.load_records() if r.provider != "mock"]
    if not records:
        raise FileNotFoundError(f"nenhuma execução do piloto (com gerador real) em {store.root}")
    rows = failure_rows(records)
    csv_path = store.root / "failure_report.csv"
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:  # utf-8-sig: abre certo no Excel
        writer = csv.DictWriter(f, fieldnames=_FIELDS, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)

    lines = ["# Relatório de falhas do piloto", "",
             "Preencha a coluna `classification` em `failure_report.csv` com: " + ", ".join(f"`{c}`" for c in CLASSES) + ".",
             "Só `test_defect` e `adapter_gap` autorizam mudar `oracles/` (registre em `oracles/CHANGELOG.md`).", "",
             "## Taxas por modelo", "",
             "| modelo | execuções | status | formato ok | contrato ok (sobre formato) | build ok (sobre contrato) | executável | truncadas | recusas |",
             "|---|---|---|---|---|---|---|---|---|"]
    by_model: dict[str, list[RunRecord]] = {}
    for rec in records:
        by_model.setdefault(f"{rec.provider}:{rec.model_id_requested}", []).append(rec)
    for model, recs in sorted(by_model.items()):
        status = ", ".join(f"{k}={v}" for k, v in sorted(Counter(r.status for r in recs).items()))
        fmt = [r for r in recs if r.status not in ("truncated", "refusal", "api_error", "model_mismatch")]
        ok_fmt = [r for r in fmt if r.exec.format_ok]
        ok_ctr = [r for r in ok_fmt if r.exec.contract_ok]
        lines.append(
            f"| {model} | {len(recs)} | {status} | {_rate([r.exec.format_ok for r in fmt])} | {_rate([bool(r.exec.contract_ok) for r in ok_fmt])} "
            f"| {_rate([bool(r.exec.build_ok) for r in ok_ctr])} | {_rate([bool(r.exec.executable) for r in ok_ctr])} "
            f"| {sum(r.status == 'truncated' for r in recs)} | {sum(r.status == 'refusal' for r in recs)} |"
        )
    lines += ["", "## Nota funcional por execução", "", "| execução | status | accuracy_a | accuracy_b |", "|---|---|---|---|"]
    for rec in records:
        f = rec.functional
        fmt_acc = lambda v: "—" if v is None else f"{v:.2f}"
        lines.append(f"| {rec.run_id} | {rec.status} | {fmt_acc(f.accuracy_a if f else None)} | {fmt_acc(f.accuracy_b if f else None)} |")
    lines += ["", "## Casos que não deram YES", ""]
    current = None
    for row in rows:
        if row["run_id"] != current:
            current = row["run_id"]
            lines += ["", f"### {current}", f"`specui serve --run-id {current}` abre este app no navegador.", ""]
        if row["case_id"] == "—":
            lines.append(f"- **{row['status']}** (sem app para testar): {row['error']}")
        else:
            blocked = " (bloqueado: pré-condição)" if row["blocked"] else ""
            detail = row["failed_assertions"] or row["error"]
            lines.append(f"- `{row['case_id']}` **{row['outcome']}**{blocked}: {detail}")
    md_path = store.root / "failure_report.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return {"markdown": md_path, "csv": csv_path}
