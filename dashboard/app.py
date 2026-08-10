import sys
import json
import os
from pathlib import Path
import pandas as pd
import streamlit as st

# ----------------------------------------------------
# 1. SYS PATH SETUP (Garantir importação da pasta 'src')
# ----------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

try:
    from loaders import BenchmarkDataLoader
except ImportError:
    try:
        from src.loaders import BenchmarkDataLoader
    except ImportError:
        BenchmarkDataLoader = None

# ----------------------------------------------------
# 2. STREAMLIT CONFIG
# ----------------------------------------------------
st.set_page_config(
    page_title="SPEC-UI (Specification-Driven UI Evaluation Framework)",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

RESULTS_PATH = ROOT_DIR / "results" / "eval_results.json"
ARTIFACTS_DIR = ROOT_DIR / "results" / "artifacts"
SCREENSHOTS_DIR = ROOT_DIR / "results" / "screenshots"

# ----------------------------------------------------
# 3. DATA LOADERS (Opção 2 Integrada)
# ----------------------------------------------------
@st.cache_data
def _load_data():
    """Carrega os dados em JSON e os itens do benchmark de forma resiliente."""
    results = []
    if RESULTS_PATH.exists():
        try:
            with open(RESULTS_PATH, "r", encoding="utf-8") as f:
                results = json.load(f)
        except Exception as e:
            st.error(f"Erro ao carregar 'eval_results.json': {e}")

    benchmark_items = []
    if BenchmarkDataLoader is not None:
        try:
            data_dir = ROOT_DIR / "data"
            benchmarks_dir = ROOT_DIR / "benchmarks"
            loader = BenchmarkDataLoader(data_dir=data_dir, benchmarks_dir=benchmarks_dir) if "data_dir" in BenchmarkDataLoader.__init__.__code__.co_varnames else BenchmarkDataLoader()
            
            # --- OPÇÃO 2: Verificação do método correto ---
            if hasattr(loader, "load_all"):
                benchmark_items = loader.load_all()
            elif hasattr(loader, "load"):
                benchmark_items = loader.load(benchmarks_dir)
        except Exception as e:
            st.warning(f"Aviso ao carregar BenchmarkDataLoader: {e}")

    return results, benchmark_items

# ----------------------------------------------------
# 4. DASHBOARD PRINCIPAL
# ----------------------------------------------------
def main():
    st.title("SPEC-UI (Specification-Driven UI Evaluation Framework) Dashboard")
    st.caption("Análise comparativa de geração de código Frontend: **No_Spec** vs **With_Spec**")

    results, benchmark_items = _load_data()

    if not results:
        st.warning(f"Nenhum resultado encontrado em `{RESULTS_PATH}`. Execute `python main.py` primeiro!")
        st.stop()

    df = pd.DataFrame(results)

    # Garantia de colunas básicas
    if "visual_score" not in df.columns:
        df["visual_score"] = 0
    if "visual_verdict" not in df.columns:
        df["visual_verdict"] = "FAIL"
    if "prompt_type" not in df.columns:
        df["prompt_type"] = "Unknown"

    if "complexity" not in df.columns:
        def extract_complexity(item_id):
            id_str = str(item_id).lower()
            if "easy" in id_str:
                return "Easy"
            elif "medium" in id_str:
                return "Medium"
            elif "hard" in id_str:
                return "Hard"
            return "Unknown"
        df["complexity"] = df["item_id"].apply(extract_complexity)

    # ----------------------------------------------------
    # FILTROS LATERAIS
    # ----------------------------------------------------
    st.sidebar.header("Filtros de Visualização")

    all_benchmarks = list(df["benchmark_name"].unique()) if "benchmark_name" in df.columns else []
    selected_benchmarks = st.sidebar.multiselect("Benchmarks", all_benchmarks, default=all_benchmarks)

    all_complexities = ["Easy", "Medium", "Hard"]
    selected_complexities = st.sidebar.multiselect("Complexidade", all_complexities, default=all_complexities)

    all_prompts = list(df["prompt_type"].unique())
    selected_prompts = st.sidebar.multiselect("Modo do Prompt", all_prompts, default=all_prompts)

    filtered_df = df.copy()
    if selected_benchmarks and "benchmark_name" in filtered_df.columns:
        filtered_df = filtered_df[filtered_df["benchmark_name"].isin(selected_benchmarks)]
    if selected_complexities:
        filtered_df = filtered_df[filtered_df["complexity"].isin(selected_complexities)]
    if selected_prompts:
        filtered_df = filtered_df[filtered_df["prompt_type"].isin(selected_prompts)]

    # ----------------------------------------------------
    # CARDS DE MÉTRICAS (KPIS)
    # ----------------------------------------------------
    total_tests = len(filtered_df)
    passed_tests = len(filtered_df[filtered_df["visual_verdict"] == "PASS"])
    pass_rate = (passed_tests / total_tests * 100) if total_tests > 0 else 0
    avg_score = filtered_df["visual_score"].mean() if total_tests > 0 else 0

    spec_wins = 0
    total_pairs = 0
    unique_items = filtered_df["item_id"].unique() if "item_id" in filtered_df.columns else []

    for i_id in unique_items:
        item_df = filtered_df[filtered_df["item_id"] == i_id]
        no_s = item_df[item_df["prompt_type"] == "No_Spec"]
        with_s = item_df[item_df["prompt_type"] == "With_Spec"]
        if not no_s.empty and not with_s.empty:
            total_pairs += 1
            if with_s["visual_score"].values[0] > no_s["visual_score"].values[0]:
                spec_wins += 1

    spec_win_rate = (spec_wins / total_pairs * 100) if total_pairs > 0 else 0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total de Testes", total_tests)
    col2.metric("Média Visual", f"{avg_score:.1f} / 100")
    col3.metric("Taxa de Aprovação", f"{pass_rate:.1f}%", f"{passed_tests}/{total_tests}")
    col4.metric("Spec Win Rate", f"{spec_win_rate:.1f}%", f"{spec_wins}/{total_pairs} pares")

    st.divider()

    # ----------------------------------------------------
    # TABS INTERATIVAS
    # ----------------------------------------------------
    tab1, tab2, tab4 = st.tabs([
        "📊 Visão Geral",
        "🧩 No_Spec vs With_Spec",
        "🔎 Inspeção de Artefatos"
    ])

    # TAB 1: VISÃO GERAL
    with tab1:
        st.subheader("Desempenho por Complexidade e Prompt")
        if not filtered_df.empty:
            chart_data = filtered_df.groupby(["complexity", "prompt_type"])["visual_score"].mean().reset_index()
            st.bar_chart(
                chart_data,
                x="complexity",
                y="visual_score",
                color="prompt_type",
                stack=False
            )

        st.subheader("Tabela Geral de Resultados")
        disp_cols = ["item_id", "benchmark_name", "complexity", "prompt_type", "visual_score", "visual_verdict", "execution_time_ms"]
        available_disp_cols = [c for c in disp_cols if c in filtered_df.columns]
        st.dataframe(filtered_df[available_disp_cols], use_container_width=True)

    # TAB 2: NO_SPEC vs WITH_SPEC
    with tab2:
        st.subheader("Estratégias de Prompt: Sem Especificação vs Com Especificação")
        
        no_spec_df = filtered_df[filtered_df["prompt_type"] == "No_Spec"]
        with_spec_df = filtered_df[filtered_df["prompt_type"] == "With_Spec"]

        c1, c2 = st.columns(2)
        with c1:
            st.markdown("### Modo: No_Spec")
            avg_no = no_spec_df["visual_score"].mean() if not no_spec_df.empty else 0
            pass_no = (len(no_spec_df[no_spec_df["visual_verdict"] == "PASS"]) / len(no_spec_df) * 100) if not no_spec_df.empty else 0
            st.metric("Média de Nota", f"{avg_no:.2f}")
            st.metric("Taxa de Aprovação", f"{pass_no:.1f}%")

        with c2:
            st.markdown("### Modo: With_Spec")
            avg_with = with_spec_df["visual_score"].mean() if not with_spec_df.empty else 0
            pass_with = (len(with_spec_df[with_spec_df["visual_verdict"] == "PASS"]) / len(with_spec_df) * 100) if not with_spec_df.empty else 0
            st.metric("Média de Nota", f"{avg_with:.2f}", f"{avg_with - avg_no:+.2f} pts")
            st.metric("Taxa de Aprovação", f"{pass_with:.1f}%", f"{pass_with - pass_no:+.1f}%")

        st.divider()
        st.markdown("### Comparativo por Tarefa")
        
        comparison_list = []
        for i_id in unique_items:
            item_df = filtered_df[filtered_df["item_id"] == i_id]
            no_row = item_df[item_df["prompt_type"] == "No_Spec"]
            with_row = item_df[item_df["prompt_type"] == "With_Spec"]

            if not no_row.empty and not with_row.empty:
                score_no = no_row["visual_score"].values[0]
                score_with = with_row["visual_score"].values[0]
                bench = no_row["benchmark_name"].values[0] if "benchmark_name" in no_row.columns else ""
                comp = no_row["complexity"].values[0] if "complexity" in no_row.columns else ""

                comparison_list.append({
                    "ID": i_id,
                    "Benchmark": bench,
                    "Complexidade": comp,
                    "Nota No_Spec": score_no,
                    "Nota With_Spec": score_with,
                    "Diferença": score_with - score_no,
                    "Vencedor": "With_Spec" if score_with > score_no else ("No_Spec" if score_no > score_with else "Empate")
                })

        if comparison_list:
            st.dataframe(pd.DataFrame(comparison_list), use_container_width=True)

        st.subheader("Comparativo entre Suítes de Benchmark")
        
        if "benchmark_name" in filtered_df.columns:
            bench_summary = filtered_df.groupby(["benchmark_name", "prompt_type"]).agg(
                Media_Nota=("visual_score", "mean"),
                Total=("visual_score", "count"),
                Aprovados=("visual_verdict", lambda x: (x == "PASS").sum())
            ).reset_index()

            bench_summary["Taxa_Aprovacao_%"] = (bench_summary["Aprovados"] / bench_summary["Total"]) * 100
            st.dataframe(bench_summary, use_container_width=True)

            st.bar_chart(
                bench_summary,
                x="benchmark_name",
                y="Media_Nota",
                color="prompt_type",
                stack=False
            )

    # TAB 4: INSPEÇÃO INDIVIDUAL
    with tab4:
        st.subheader("Auditoria de Telas e Código HTML")
        
        selected_item_id = st.selectbox("Selecione o Item do Benchmark", df["item_id"].unique())
        selected_mode = st.radio("Modo do Prompt", ["No_Spec", "With_Spec"], horizontal=True)

        item_records = df[(df["item_id"] == selected_item_id) & (df["prompt_type"] == selected_mode)]

        if not item_records.empty:
            rec = item_records.iloc[0]

            c1, c2 = st.columns([1, 1])

            with c1:
                st.markdown("#### 📊 Parecer do Juiz Visual")
                st.write(f"**Benchmark:** {rec.get('benchmark_name', 'N/A')}")
                st.write(f"**Nota:** {rec.get('visual_score', 0)} / 100")
                st.write(f"**Status:** {rec.get('visual_verdict', 'N/A')}")

                feedback_data = rec.get("visual_feedback", {})
                if isinstance(feedback_data, dict):
                    st.json(feedback_data)
                else:
                    st.info(f"Feedback: {rec.get('feedback', feedback_data)}")

            with c2:
                st.markdown("#### Captura Playwright")
                shot_path = SCREENSHOTS_DIR / f"{selected_item_id}_{selected_mode}.png"
                if shot_path.exists():
                    st.image(str(shot_path), caption=f"Screenshot: {selected_item_id} ({selected_mode})")
                else:
                    st.warning("Screenshot não localizado na pasta `results/screenshots/`.")

            st.divider()
            st.markdown("#### HTML Renderizado")
            html_path = ARTIFACTS_DIR / f"{selected_item_id}_{selected_mode}.html"
            if html_path.exists():
                st.code(html_path.read_text(encoding="utf-8"), language="html")
            elif "raw_code" in rec and rec["raw_code"]:
                st.code(rec["raw_code"], language="html")


if __name__ == "__main__":
    main()