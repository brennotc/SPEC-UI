import os
import sys
import json
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
SRC_DIR = BASE_DIR / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

load_dotenv()

from models import BenchmarkItem
from loaders import BenchmarkDataLoader
from generator import CodeGenerator
from evaluator import CodeEvaluator


def get_sort_key(item: BenchmarkItem) -> tuple:
    id_lower = item.id.lower()
    bench_lower = item.benchmark_name.lower()

    if "easy" in id_lower:
        diff_rank = 0
    elif "medium" in id_lower:
        diff_rank = 1
    elif "hard" in id_lower:
        diff_rank = 2
    else:
        diff_rank = 3

    if "ui" in bench_lower:
        bench_rank = 0
    elif "design" in bench_lower:
        bench_rank = 1
    else:
        bench_rank = 2

    return (diff_rank, bench_rank, item.id)


def main():
    print("==============================================================================================")
    print("     INICIANDO SPEC-UI (Specification-Driven UI Evaluation Framework)    ")
    print("==============================================================================================")

    loader = BenchmarkDataLoader(data_dir=BASE_DIR / "data", benchmarks_dir=BASE_DIR / "benchmarks")
    all_loaded = loader.load_all()

    TARGET_CATEGORIES = ["easy", "medium", "hard"]

    filtered_items = []
    for item in all_loaded:
        id_lower = item.id.lower()
        if any(cat in id_lower for cat in TARGET_CATEGORIES):
            filtered_items.append(item)

    if not filtered_items:
        print("Nenhum item (easy, medium, hard) localizado!")
        return

    filtered_items.sort(key=get_sort_key)

    print(f"Total de itens filtrados e ordenados: {len(filtered_items)}")

    generator = CodeGenerator()
    evaluator = CodeEvaluator()

    artifacts_dir = BASE_DIR / "results" / "artifacts"
    results_dir = BASE_DIR / "results"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    results = []

    print("\n=========================================================")
    print("FASE DE AVALIAÇÃO VISUAL E MÉTRICAS (LLM-AS-A-JUDGE)")
    print(f"Modelo Gerador: {generator.model_name}")
    print(f"Modelo Juiz: {evaluator.model_name}")
    print("=========================================================\n")

    for item in filtered_items:
        for prompt_type in ["No_Spec", "With_Spec"]:
            print(f"[Avaliação] {item.benchmark_name.upper()} | {item.id} | Modo: {prompt_type}")

            prompt = item.prompt_with_spec if prompt_type == "With_Spec" else item.prompt_no_spec
            artifact_file = artifacts_dir / f"{item.id}_{prompt_type}.html"

            if artifact_file.exists():
                print(f"HTML existente em 'artifacts/'. Lendo arquivo...")
                generated_code = artifact_file.read_text(encoding="utf-8")
            else:
                print(f"HTML não encontrado. Gerando código via API ({generator.model_name})...")
                generated_code = generator.generate_code(prompt=prompt, item_id=item.id)
                artifact_file.write_text(generated_code, encoding="utf-8")

            eval_res = evaluator.evaluate(
                item=item,
                prompt_type=prompt_type,
                generated_code=generated_code,
                artifact_path=artifact_file
            )

            results.append(eval_res)
            
            if hasattr(eval_res, 'visual_feedback') and isinstance(eval_res.visual_feedback, dict):
                feedback_text = eval_res.visual_feedback.get('feedback', '')
            elif hasattr(eval_res, 'feedback'):
                feedback_text = str(eval_res.feedback)
            else:
                feedback_text = "Sem feedback detalhado"

            print(f"Nota Visual: {eval_res.visual_score}/100 | Status: {eval_res.visual_verdict}")
            print(f"Crítica do Juiz: {feedback_text}\n")

    # SALVA O JSON COMPLETO PARA O DASHBOARD (STREAMLIT)
    results_json_path = results_dir / "eval_results.json"
    serialized_results = []
    for r in results:
        if hasattr(r, "model_dump"):
            serialized_results.append(r.model_dump())
        elif hasattr(r, "dict"):
            serialized_results.append(r.dict())
        else:
            serialized_results.append(r.__dict__)

    with open(results_json_path, "w", encoding="utf-8") as f:
        json.dump(serialized_results, f, indent=2, ensure_ascii=False)

    print(f"Resultados salvos com sucesso em: {results_json_path}")

    # =========================================================
    #     RELATÓRIO ESTATÍSTICO E COMPARATIVO FINAL
    # =========================================================
    print("\n=========================================================")
    print("  RELATÓRIO COMPARATIVO FINAL DOS EXPERIMENTOS")
    print("=========================================================")
    
    total_evals = len(results)
    passed_total = sum(1 for r in results if r.visual_verdict == "PASS")
    avg_total = sum(r.visual_score for r in results) / total_evals if total_evals else 0

    print(f"• Total de Testes Executados : {total_evals}")
    print(f"• Média Geral de Nota Visual : {avg_total:.2f}/100")
    print(f"• Taxa Geral de Aprovados   : {(passed_total / total_evals) * 100:.1f}% ({passed_total}/{total_evals})")

    # 1. NO_SPEC vs WITH_SPEC
    no_spec = [r for r in results if r.prompt_type == "No_Spec"]
    with_spec = [r for r in results if r.prompt_type == "With_Spec"]

    avg_no = sum(r.visual_score for r in no_spec) / len(no_spec) if no_spec else 0
    avg_with = sum(r.visual_score for r in with_spec) / len(with_spec) if with_spec else 0
    pass_no = sum(1 for r in no_spec if r.visual_verdict == "PASS")
    pass_with = sum(1 for r in with_spec if r.visual_verdict == "PASS")

    # Win Rate da Spec (Quantas vezes With_Spec superou No_Spec na mesma tarefa)
    item_ids = list(set(r.item_id for r in results))
    spec_wins = 0
    for i_id in item_ids:
        r_no = next((r for r in no_spec if r.item_id == i_id), None)
        r_with = next((r for r in with_spec if r.item_id == i_id), None)
        if r_no and r_with and r_with.visual_score > r_no.visual_score:
            spec_wins += 1

    win_rate_spec = (spec_wins / len(item_ids)) * 100 if item_ids else 0

    print("\n--- ESTRATÉGIA DE PROMPT (NO_SPEC vs WITH_SPEC) ---")
    print(f"• No_Spec   → Média Nota: {avg_no:.2f}/100 | Pass Rate: {(pass_no/len(no_spec))*100 if no_spec else 0:.1f}%")
    print(f"• With_Spec → Média Nota: {avg_with:.2f}/100 | Pass Rate: {(pass_with/len(with_spec))*100 if with_spec else 0:.1f}%")
    print(f"• Impacto da Especificação (Delta Média) : {avg_with - avg_no:+.2f} pontos")
    print(f"• Spec Win Rate (With_Spec > No_Spec)     : {win_rate_spec:.1f}%")

    # 2. UIBENCH vs DESIGNBENCH
    ui_bench = [r for r in results if "ui" in r.benchmark_name.lower()]
    design_bench = [r for r in results if "design" in r.benchmark_name.lower()]

    avg_ui = sum(r.visual_score for r in ui_bench) / len(ui_bench) if ui_bench else 0
    avg_db = sum(r.visual_score for r in design_bench) / len(design_bench) if design_bench else 0
    pass_ui = sum(1 for r in ui_bench if r.visual_verdict == "PASS")
    pass_db = sum(1 for r in design_bench if r.visual_verdict == "PASS")

    print("\n---  COMPARATIVO ENTRE BENCHMARKS (UIBENCH vs DESIGNBENCH) ---")
    print(f"• UI-Bench     → Média Nota: {avg_ui:.2f}/100 | Pass Rate: {(pass_ui/len(ui_bench))*100 if ui_bench else 0:.1f}%")
    print(f"• DesignBench  → Média Nota: {avg_db:.2f}/100 | Pass Rate: {(pass_db/len(design_bench))*100 if design_bench else 0:.1f}%")

    # 3. MATRIZ DE DIFICULDADE
    print("\n---  MATRIZ POR DIFICULDADE E MODO ---")
    print(f"{'Dificuldade':<12} | {'Benchmark':<12} | {'Prompt':<10} | {'Média Visual':<12} | {'Aprovação'}")
    print("-" * 65)
    
    for diff in ["easy", "medium", "hard"]:
        for bench_name in ["UIBench", "DesignBench"]:
            for p_type in ["No_Spec", "With_Spec"]:
                group = [
                    r for r in results 
                    if diff in r.item_id.lower() 
                    and bench_name.lower() in r.benchmark_name.lower()
                    and r.prompt_type == p_type
                ]
                if group:
                    g_avg = sum(r.visual_score for r in group) / len(group)
                    g_pass = sum(1 for r in group if r.visual_verdict == "PASS")
                    print(f"{diff.capitalize():<12} | {bench_name:<12} | {p_type:<10} | {g_avg:<12.2f} | {g_pass}/{len(group)} PASS")

    print("=========================================================\n")


if __name__ == "__main__":
    main()