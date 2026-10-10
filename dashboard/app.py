"""Painel SPEC-UI (Streamlit): `streamlit run dashboard/app.py`.

Lê só `results/` da execução PRINCIPAL (`results/aggregate/` e os records); o piloto (`results/pilot/`) nunca aparece.
Nenhuma nota vem de juiz: tudo é métrica automática (Design2Code, Figma2Code, WebGen-Bench).
"""

import json
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from specui.analysis import AnalysisRefused
from specui.analysis.contrasts import forest_figure
from specui.analysis.items import item_analysis
from specui.analysis.panel import free_rows, grid, load_main, status_counts
from specui.analysis.report import analyze_frame
from specui.config import load_config

st.set_page_config(page_title="SPEC-UI", layout="wide")
st.title("SPEC-UI: a especificação formal ajuda a gerar front-end?")


@st.cache_data(show_spinner="Lendo results/ ...")
def _load(results_dir: str):
    records, df = load_main(results_dir)
    return records, df


cfg = load_config(ROOT / "configs" / "default.yaml")
results_dir = st.sidebar.text_input("Pasta de resultados", str(cfg.path("results_dir")))
records, df = _load(results_dir)
if df.empty:
    st.info("Nenhuma execução principal em results/. Rode `specui run` (o piloto fica em results/pilot/ e não aparece aqui).")
    st.stop()

df["model"] = df["provider"] + ":" + df["model_id_requested"]
models = sorted(df["model"].unique())
chosen = st.sidebar.multiselect("Modelos", models, default=models)
view = df[df["model"].isin(chosen)]
st.sidebar.caption(f"{len(view)} execuções · oráculo: {', '.join(sorted(df.get('oracle_suite_tag', pd.Series(dtype=str)).dropna().unique())) or 'sem tag'}")

tabs = st.tabs(["Grade de células", "Contraste da spec", "Oráculo e itens", "Qualidade de código", "Inspeção de execução", "Prompts livres"])

# --------------------------------------------------------------------------- 1. grade
with tabs[0]:
    st.subheader("Células por modelo")
    g = grid(view)
    st.dataframe(g, use_container_width=True)
    st.caption("Formato sobre todas as gerações; contrato sobre as de formato ok; build e executabilidade sobre as de contrato ok. "
               "`accuracy_a` e `ves` só contam quem executou (condicional).")
    st.dataframe(status_counts(view), use_container_width=True)

# --------------------------------------------------------------------------- 2. contraste
with tabs[1]:
    st.subheader("Efeito da spec (accuracy_a, ITT)")
    try:
        analysis = analyze_frame(df, cfg, records)
    except (AnalysisRefused, ValueError) as exc:
        st.error(f"A análise recusou os dados: {exc}")
        analysis = None
    if analysis:
        res_itt, res_cond = analysis["_results"]
        if res_itt:
            st.plotly_chart(forest_figure(res_itt, (analysis.get("consistency") or {}).get("differences")), use_container_width=True)
            st.dataframe(pd.DataFrame([r.as_dict() for r in res_itt.values()]).drop(columns=["strata"]), use_container_width=True)
        st.markdown("**Δ por tarefa × modalidade × modelo (ITT)**")
        strata = pd.DataFrame(analysis["strata_itt"])
        if not strata.empty:
            st.plotly_chart(px.bar(strata, x="task_id", y="delta", color="model", facet_col="modality", barmode="group",
                                   error_y=strata["ci_high"] - strata["delta"], error_y_minus=strata["delta"] - strata["ci_low"]),
                            use_container_width=True)
            st.markdown("**Texto × multimodal** (Δ médio por modalidade)")
            by_modality = strata.groupby(["model", "modality"])["delta"].mean().reset_index()
            st.dataframe(by_modality, use_container_width=True)
        with st.expander("Condicional (só executáveis) e taxa de executabilidade"):
            st.dataframe(pd.DataFrame([r.as_dict() for r in res_cond.values()]).drop(columns=["strata"], errors="ignore"), use_container_width=True)
            st.dataframe(pd.DataFrame(analysis["executability"]), use_container_width=True)
        with st.expander("Consistência entre modelos"):
            cons = analysis.get("consistency") or {}
            st.write(f"Estratos com o mesmo sinal em todos os modelos: {cons.get('n_strata_same_sign')} de {cons.get('n_strata')}")
            st.dataframe(pd.DataFrame(cons.get("signs", [])), use_container_width=True)
            st.dataframe(pd.DataFrame(cons.get("differences", [])), use_container_width=True)
            st.caption("Leitura: robustez do efeito nos modelos testados; interação não significativa não é igualdade.")

# --------------------------------------------------------------------------- 3. oráculo
with tabs[2]:
    st.subheader("Análise de itens")
    items = item_analysis([r for r in records if f"{r.provider}:{r.model_id_requested}" in chosen])
    if items.empty:
        st.info("Sem casos executados ainda.")
    else:
        st.dataframe(items, use_container_width=True)
        st.caption("flag_floor: 0 % em todas as condições · flag_ceiling: 100 % em todas · blocked_rate: pré-condição falhou.")
        st.plotly_chart(px.bar(items, x="case_id", y="mean_score", color="level", hover_data=["task_id"]), use_container_width=True)

# --------------------------------------------------------------------------- 4. código
with tabs[3]:
    st.subheader("Qualidade de código (Figma2Code) × fidelidade visual")
    cols = ["cq_rur", "cq_apr", "cq_fu", "cq_bc", "cq_str", "cq_avu", "cq_isr", "cq_ccr"]
    present = [c for c in cols if c in view]
    if present and "emb_ves_dinov2" in view:
        st.plotly_chart(px.scatter(view.dropna(subset=["emb_ves_dinov2"]), x="emb_ves_dinov2", y=present[1] if len(present) > 1 else present[0],
                                   color="prompt_kind", symbol="model", hover_data=["run_id"]), use_container_width=True)
        st.dataframe(view.groupby(["model", "prompt_kind"])[present].mean().reset_index(), use_container_width=True)
    else:
        st.info("Métricas de código/VES ainda não calculadas (`specui evaluate --all --groups code,visual`).")

# --------------------------------------------------------------------------- 5. inspeção
with tabs[4]:
    st.subheader("Inspeção de uma execução")
    run_id = st.selectbox("Execução", view["run_id"].tolist())
    rec = next(r for r in records if r.run_id == run_id)
    base = Path(results_dir) / rec.paths["run_dir"]
    left, right = st.columns(2)
    task_png = ROOT / "benchmarks" / "tasks" / rec.difficulty / f"{rec.task_id}.png"
    if task_png.is_file():
        left.image(str(task_png), caption="Design (Figma)")
    shot = base / rec.paths.get("screenshot", "screenshot.png")
    if shot.is_file():
        right.image(str(shot), caption="Render do app gerado")
    st.write({"status": rec.status, "modelo pedido": rec.model_id_requested, "modelo devolvido": rec.model_id_returned,
              "prompt sha256": rec.prompt_sha256, "envelope": rec.envelope_version, "scaffold": rec.scaffold_version,
              "oráculo": rec.oracle_suite_tag})
    if rec.functional:
        st.dataframe(pd.DataFrame([c.model_dump() for c in rec.functional.cases]), use_container_width=True)
    for title, name in (("Prompt (usuário)", "prompt.user.txt"), ("Resposta bruta", "response.raw.txt")):
        path = base / name
        if path.is_file():
            with st.expander(title):
                st.code(path.read_text(encoding="utf-8")[:20000])
    stderr = base / rec.paths["build_stderr"] if "build_stderr" in rec.paths else None
    if stderr and stderr.is_file() and stderr.read_text(encoding="utf-8").strip():
        with st.expander("Build (stderr)"):
            st.code(stderr.read_text(encoding="utf-8")[:8000])
    if rec.technical:
        with st.expander("Console / axe"):
            st.json({"console": rec.technical.console_errors, "bloqueadas": rec.technical.blocked_requests, "axe": rec.technical.axe_violations})
    pairs = base / rec.design2code.pairs_path if rec.design2code and rec.design2code.pairs_path else None
    if pairs and pairs.is_file():
        with st.expander("Pares de blocos e fusões (Design2Code)"):
            st.json(json.loads(pairs.read_text(encoding="utf-8")))
    generated = base / "generated"
    if generated.is_dir():
        with st.expander("Arquivos gerados"):
            for f in sorted(generated.rglob("*")):
                if f.is_file():
                    st.write(f.relative_to(generated).as_posix())

# --------------------------------------------------------------------------- 6. livres
with tabs[5]:
    st.subheader("Prompts livres de participantes")
    free = free_rows(view)
    if free.empty:
        st.info("Nenhuma execução de prompt livre (`specui run --prompt-sources free:<coleta>`).")
    else:
        st.dataframe(free, use_container_width=True)
        if len(free) >= 10:
            st.plotly_chart(px.scatter(free, x="in_requirement_coverage_total", y="fn_accuracy_a_restricted", color="task_id", trendline="ols"),
                            use_container_width=True)
        st.caption("O perfil dos participantes só aparece agregado e nunca com n pequeno; o texto é anônimo (p001…).")
