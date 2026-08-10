import pandas as pd
import json
from pathlib import Path
from huggingface_hub import snapshot_download

# Baixa (ou usa cache) todos os arquivos e retorna o diretório
snap_dir = snapshot_download(repo_id="AfterQuery/ui-bench", repo_type="dataset")

# Encontra o CSV principal (o que tem as 8 colunas estruturadas)
candidates = [f for f in Path(snap_dir).glob("*.csv") if "Main" in f.name or "main" in f.name]
if not candidates:
    # fallback: pega o maior CSV (Main tem 28.9k, Figma tem 10.7k)
    candidates = sorted(Path(snap_dir).glob("*.csv"), key=lambda f: f.stat().st_size, reverse=True)

local_path = candidates[0]
print(f"Lendo: {local_path.name}")
df = pd.read_csv(local_path)
print(f"Colunas: {list(df.columns)}")
print(f"Linhas: {len(df)}")

def map_complexity(item_type: str) -> str:
    return "Hard" if str(item_type).lower() == "webapp" else "Medium"

records = []
for idx, row in df.iterrows():
    title = str(row.get("Title", f"ui_{idx:03d}"))
    scenario = str(row.get("Scenario", ""))
    vibe = str(row.get("Vibe", ""))
    constraints = str(row.get("Constraints", ""))

    prompt_no = f"{title}. {row.get('Goal', '')}".strip()

    prompt_with = scenario
    if vibe and vibe != "nan":
        prompt_with += f"\n\nBrand vibe: {vibe}"
    if constraints and constraints != "nan":
        prompt_with += f"\n\nConstraints: {constraints}"

    records.append({
        "id": f"ui_{idx+1:03d}",
        "task_description": prompt_no,
        "requirements": prompt_with,
        "complexity": map_complexity(row.get("Type", "Website")),
        "sector": str(row.get("Sector", "")),
        "title": title,
    })

out = Path("data/uibench.json")
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"Saved {len(records)} items to {out}")