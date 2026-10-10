"""Orquestra a análise e escreve `results/aggregate/{analysis.json,report.md,forest.html}`.

Ordem do relatório: métrica primária (ITT) e contraste principal por modelo; condicional (com a taxa de executabilidade);
secundários; consistência entre modelos; itens; prompts livres. Redação: "nos modelos testados", nunca
"independentemente do modelo"; interação não significativa não é igualdade.
"""

import json
from pathlib import Path
from typing import Any

import pandas as pd

from specui.analysis.contrasts import (
    EffectResult,
    consistency,
    forest_figure,
    main_contrast,
    ols_robustness,
    stratum_table,
)
from specui.analysis.data import AnalysisRefused, executability, prepare_frame, spec_frame
from specui.analysis.free import contract_failure_by_source, free_frame, free_regression
from specui.analysis.items import accuracy_without_flagged, item_analysis
from specui.models import RunConfig
from specui.storage import RunStore, records_to_dataframe, write_aggregate


def _md_table(df: pd.DataFrame, floatfmt: str = "{:.3f}") -> str:
    if df.empty:
        return "_(sem dados)_\n"
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for _, row in df.iterrows():
        cells = [floatfmt.format(v) if isinstance(v, float) else str(v) for v in row]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def _effects_table(results: dict[str, EffectResult]) -> pd.DataFrame:
    return pd.DataFrame([
        {"modelo": r.model, "efeito": r.effect, "IC95 baixo": r.ci_low, "IC95 alto": r.ci_high, "p (permutação)": r.p_perm,
         "IC acima de 0": "sim" if r.ci_above_zero else "não", "estratos": r.n_strata, "runs": r.n_runs}
        for r in results.values()
    ])


def _section_contrast(title: str, results: dict[str, EffectResult]) -> str:
    out = [f"## {title}\n", _md_table(_effects_table(results))]
    out.append("Efeito = média, sobre tarefa × modalidade, de (média with_spec − média no_spec), por modelo.\n")
    skipped = {m: r.skipped for m, r in results.items() if r.skipped}
    if skipped:
        out.append(f"Estratos sem as duas fontes (ignorados): {skipped}\n")
    return "\n".join(out)


def analyze_frame(df: pd.DataFrame, cfg: RunConfig, records: list | None = None) -> dict[str, Any]:
    """Toda a análise sobre o quadro de runs (um DataFrame de `records_to_dataframe`)."""
    a = cfg.analysis
    frame = prepare_frame(df)
    itt, cond = spec_frame(frame, "accuracy_itt"), spec_frame(frame, "accuracy_cond")
    out: dict[str, Any] = {"n_runs": len(frame), "models": sorted(frame["model"].unique().tolist())}
    kwargs = {"n_boot": a.n_boot, "n_perm": a.n_perm, "alpha": a.alpha, "seed": a.seed}

    res_itt = main_contrast(itt, "accuracy_itt", **kwargs) if len(itt) else {}
    res_cond = main_contrast(cond, "accuracy_cond", **kwargs) if len(cond) else {}
    out["itt"] = {m: r.as_dict() for m, r in res_itt.items()}
    out["conditional"] = {m: r.as_dict() for m, r in res_cond.items()}
    out["executability"] = executability(frame).to_dict("records")
    out["strata_itt"] = stratum_table(res_itt).to_dict("records")
    out["consistency"] = consistency(res_itt, a.alpha, a.equivalence_margin) if res_itt else {}
    out["ols_itt"] = ols_robustness(itt, "accuracy_itt") if len(itt) else {}
    out["contract_failure"] = contract_failure_by_source(frame).to_dict("records")
    free = free_frame(frame)
    out["free"] = free_regression(free) if not free.empty else {}
    if records is not None:
        items = item_analysis(records)
        out["items"] = items.to_dict("records")
        out["accuracy_without_flagged"] = accuracy_without_flagged(records, items).to_dict("records")
    out["_results"] = (res_itt, res_cond)
    return out


def build_report(analysis: dict[str, Any], cfg: RunConfig) -> str:
    res_itt, res_cond = analysis["_results"]
    intro = (
        f"{analysis['n_runs']} runs analisadas (api_error, metric_error e model_mismatch ficam fora de qualquer conjunto). "
        f"Modelos: {', '.join(analysis['models'])}.\n"
    )
    out = ["# Relatório SPEC-UI\n", intro]
    out.append(_section_contrast("Métrica primária: accuracy_a, conjunto ITT (contraste principal)", res_itt))
    out.append(
        "ITT: toda geração tentada entra; formato, contrato, build, recusa e truncamento valem 0. "
        "Bootstrap estratificado e permutação estratificada, 10 000 réplicas.\n"
    )
    out.append(_section_contrast("Conjunto condicional (só executáveis; secundário)", res_cond))
    ex = pd.DataFrame(analysis["executability"])
    out += ["### Taxa de executabilidade (acompanha o condicional)\n", _md_table(ex)]
    strata = pd.DataFrame(analysis["strata_itt"])
    out += ["## Δ por tarefa × modalidade × modelo (ITT, secundário)\n", _md_table(strata)]

    cons = analysis.get("consistency") or {}
    out.append("## Consistência entre modelos\n")
    if cons:
        out.append(f"Estratos em que todos os modelos têm o mesmo sinal de Δ: {cons['n_strata_same_sign']} de {cons['n_strata']}.\n")
        out.append(_md_table(pd.DataFrame(cons["signs"])))
        diffs = pd.DataFrame(cons["differences"])
        out += ["Diferença entre os efeitos médios (IC 95 %):\n", _md_table(diffs)]
        tost = cons["tost"]
        out.append("Equivalência (TOST): " + (f"margem {tost['margin']}; ver coluna `equivalent`.\n" if tost["ran"] else f"não executada: {tost['reason']}.\n"))
        out.append("Leitura: o fator modelo testa a robustez do efeito **nos modelos testados**; um IC que inclui zero ou uma "
                   "interação não significativa **não** é evidência de igualdade e o fator modelo não compara modelos entre si.\n")
    ols = analysis.get("ols_itt") or {}
    if ols and "coefficients" in ols:
        out += ["## Robustez: OLS com erros HC3 (ITT)\n", f"`{ols['formula']}` (n={ols['n']})\n", _md_table(pd.DataFrame(ols["coefficients"]))]
    out += ["## `contract_failure` por fonte do prompt\n", _md_table(pd.DataFrame(analysis["contract_failure"]))]
    if analysis.get("items"):
        out += ["## Análise de itens\n", _md_table(pd.DataFrame(analysis["items"])),
                "Nota de nível A com e sem os casos de piso/teto:\n", _md_table(pd.DataFrame(analysis["accuracy_without_flagged"]))]
    if analysis.get("free"):
        out += ["## Prompts livres\n", f"```json\n{json.dumps(analysis['free'], ensure_ascii=False, indent=1)[:4000]}\n```\n"]
    return "\n".join(out)


def run_analysis(cfg: RunConfig, out_dir: Path | None = None) -> dict[str, Path]:
    """`specui analyze`: lê results/ (main), valida, analisa e escreve o relatório. O piloto nunca entra."""
    store = RunStore(cfg.path("results_dir"), "main")
    records = store.load_records()
    if not records:
        raise AnalysisRefused(f"nenhuma execução principal em {store.root}")
    check_frozen_meta(store, cfg)
    df = records_to_dataframe(records)
    out_dir = out_dir or store.root / "aggregate"
    paths = write_aggregate(df, out_dir)
    analysis = analyze_frame(df, cfg, records)
    res_itt, _ = analysis["_results"]
    serializable = {k: v for k, v in analysis.items() if k != "_results"}
    paths["analysis"] = out_dir / "analysis.json"
    paths["analysis"].write_text(json.dumps(serializable, ensure_ascii=False, indent=2, default=str), encoding="utf-8", newline="\n")
    paths["report"] = out_dir / "report.md"
    paths["report"].write_text(build_report(analysis, cfg), encoding="utf-8", newline="\n")
    if res_itt:
        diffs = (analysis.get("consistency") or {}).get("differences")
        paths["forest"] = out_dir / "forest.html"
        forest_figure(res_itt, diffs).write_html(str(paths["forest"]))
    return paths


# ----------------------------------------------------------------------------- congelamento da margem


def check_frozen_meta(store: RunStore, cfg: RunConfig) -> None:
    """A margem de equivalência é gravada no início da execução principal; mudar depois invalida o TOST."""
    meta = store.read_meta()
    if meta is None:
        return
    if meta.get("equivalence_margin") != cfg.analysis.equivalence_margin:
        raise AnalysisRefused(
            f"analysis.equivalence_margin mudou depois do congelamento (run_meta.json: {meta.get('equivalence_margin')}, "
            f"config atual: {cfg.analysis.equivalence_margin})"
        )
