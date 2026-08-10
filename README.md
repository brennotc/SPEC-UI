# SPEC-UI (Specification-Driven UI Evaluation Framework)

A framework for benchmarking Large Language Models (LLMs) on front-end HTML/CSS generation tasks.
It compares prompt strategies (**Prompt Without Spec** vs **Prompt With Spec**) across multiple benchmark suites (**UI-Bench** and **DesignBench**), evaluating code execution, visual rendering, and design compliance.

---

### Project Architecture

```
eval_framework/
├── benchmarks/              ← Markdown benchmark definitions
├── dashboard/
│   └── app.py               ← Interactive Streamlit dashboard
├── data/                    ← Converted datasets (JSON)
│   ├── designbench.json
│   └── uibench.json
├── src/
│   ├── __init__.py
│   ├── evaluator.py         ← Visual & static code evaluation
│   ├── generator.py         ← LLM code generation engine
│   ├── loaders.py           ← Benchmark loaders
│   ├── metrics.py           ← Aggregation & statistical KPI export
│   ├── models.py            ← Pydantic schemas (BenchmarkItem, EvalResult, etc.)
│   ├── rate_limiter.py      ← API rate limit handling
│   └── runner.py            ← Evaluation pipeline orchestration
├── .env.example             ← Template for environment variables
├── .gitignore               ← Excluded files (keys, caches, raw datasets)
├── check_models.py          ← Diagnostic tool for Gemini API key & active models
├── convert_designbench.py   ← Pre-processor for DesignBench raw files
├── convert_uibench.py       ← Converter for HuggingFace UI-Bench dataset
├── main.py                  ← CLI entry point
├── README.md
└── requirements.txt
```

---

### Quickstart Guide

### 1. Prerequisites
- **Python 3.11+** installed.

### 2. Environment Setup

Clone the repository and set up a virtual environment:

```bash
git clone [https://github.com/your-username/eval_framework.git](https://github.com/your-username/eval_framework.git)
cd eval_framework

python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

Install the dependencies and setup Playwright browser binaries:

```bash
pip install -r requirements.txt
playwright install chromium
```

### 3. API Keys Setup

Copy `.env.example` to `.env` and fill in your Gemini/Google API key:

```bash
cp .env.example .env
```

Edit `.env`:
```env
GEMINI_API_KEY=your_actual_api_key_here
```

Test your API connection and check available models:

```bash
python check_models.py
```

---

### Data Preparation

Before running evaluations, convert the benchmark datasets into normalized JSON representations:

1. **Convert UI-Bench (from HuggingFace):**
   ```bash
   python convert_uibench.py
   ```

2. **Convert DesignBench (from local raw directory):**
   ```bash
   python convert_designbench.py
   ```

Outputs will be saved under the `data/` folder (`data/uibench.json` and `data/designbench.json`).

---

### Running the Evaluation

Execute the complete evaluation pipeline using:

```bash
python main.py
```

The execution flow:
1. Loads benchmark items from `data/` and `benchmarks/`.
2. Generates HTML code via the configured LLM for both `No_Spec` and `With_Spec` modes.
3. Evaluates generated pages visually and statically.
4. Saves output artifacts into `results/artifacts/` and metrics into `results/eval_results.json`.

---

### Viewing Results & Dashboard

Start the interactive Streamlit dashboard to inspect metrics, win rates, and visual screenshots:

```bash
streamlit run dashboard/app.py
```

### Dashboard Features:
- **KPI Metrics:** General visual score, pass rates, and Spec Win Rate ($With\_Spec > No\_Spec$).
- **Comparative Analysis:** Direct head-to-head performance of prompt strategies.
- **Artifact Inspector:** Audit rendered HTML code alongside Playwright screenshots.

---

### Output Artifacts

- `results/eval_results.json` — Structured JSON containing ratings, feedback, and execution stats.
- `results/artifacts/` — Generated `.html` files (`{item_id}_{prompt_type}.html`).
- `results/screenshots/` — Screen captures taken by Playwright during visual analysis.