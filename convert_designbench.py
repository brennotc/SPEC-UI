import json
from pathlib import Path
from collections import Counter

BENCH_DIR = Path("designbench_data/generation/vanilla")
OUT = Path("data/designbench.json")

DIFFICULTY_MAP = {
    "short": "Easy",
    "simple": "Easy",
    "easy": "Easy",
    "medium": "Medium",
    "med": "Medium",
    "long": "Hard",
    "complex": "Hard",
    "hard": "Hard",
}

records = []
for item_dir in sorted(BENCH_DIR.iterdir(), key=lambda p: int(p.name) if p.name.isdigit() else 9999):
    if not item_dir.is_dir():
        continue
    n = item_dir.name
    json_file = item_dir / f"{n}.json"
    png_file = item_dir / f"{n}.png"
    if not json_file.exists():
        continue

    data = json.loads(json_file.read_text(encoding="utf-8"))
    diff = data.get("difficulty", "medium").lower()
    complexity = DIFFICULTY_MAP.get(diff, "Medium")
    image_path = str(png_file.resolve()) if png_file.exists() else None

    records.append({
        "id": f"db_vanilla_{int(n):03d}",
        "complexity": complexity,
        "difficulty_raw": diff,
        # aliases reconhecidos pelo parse_designbench do loaders.py:
        "description": "Implement this webpage design using plain HTML and CSS.",
        "specification": (
            "You are an expert frontend developer. "
            "Reproduce the webpage shown in the reference screenshot using plain HTML and CSS. "
            "Requirements:\n"
            "- Output a single complete HTML file with all CSS embedded in a <style> tag\n"
            "- Match the exact layout, color scheme, typography, and spacing from the screenshot\n"
            "- Reproduce all visible UI elements: navigation, headers, content areas, footer\n"
            "- Use semantic HTML5 elements\n"
            "- Do not use JavaScript frameworks or external CSS libraries"
        ),
        "image_path": image_path,
        "framework": data.get("framework", "vanilla"),
    })

OUT.parent.mkdir(exist_ok=True)
OUT.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"Saved {len(records)} items to {OUT}")
print("Difficulty distribution:", dict(Counter(r["difficulty_raw"] for r in records)))