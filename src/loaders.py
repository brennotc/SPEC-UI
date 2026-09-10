import json
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

try:
    from .models import BenchmarkItem
except ImportError:
    from models import BenchmarkItem


class BenchmarkDataLoader:
    def __init__(self, data_dir: Path = Path("data"), benchmarks_dir: Path = Path("benchmarks")):
        self.data_dir = Path(data_dir)
        self.benchmarks_dir = Path(benchmarks_dir)

    def _normalize_dict(self, raw_dict: Dict[str, Any], default_benchmark_name: str) -> Dict[str, Any]:
        item_id = str(raw_dict.get("id", raw_dict.get("task_id", "ui_item_001")))

        benchmark_name = raw_dict.get("benchmark_name") or raw_dict.get("benchmark") or default_benchmark_name

        prompt_no_spec = (
            raw_dict.get("prompt_no_spec")
            or raw_dict.get("task_description")
            or raw_dict.get("prompt")
            or raw_dict.get("description")
            or "Crie uma interface web moderna para este componente."
        )

        # "requirements" is the with-spec field used by UIBench JSON
        prompt_with_spec = (
            raw_dict.get("prompt_with_spec")
            or raw_dict.get("specification")
            or raw_dict.get("spec")
            or raw_dict.get("requirements")
            or prompt_no_spec
        )

        complexity = str(raw_dict.get("complexity", "Unknown"))
        image_path = raw_dict.get("image_path") or raw_dict.get("image") or raw_dict.get("reference_image")
        multimodal = image_path is not None

        return {
            "id": item_id,
            "benchmark_name": benchmark_name,
            "prompt_no_spec": prompt_no_spec,
            "prompt_with_spec": prompt_with_spec,
            "complexity": complexity,
            "source": "official",
            "multimodal": multimodal,
            "image_path": str(image_path) if image_path else None,
        }

    def _parse_markdown_benchmark(self, text: str) -> Tuple[str, str, str]:
        """Returns (prompt_no_spec, prompt_with_spec, complexity) from a markdown file."""
        content = text
        frontmatter: Dict[str, str] = {}
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                for line in parts[1].splitlines():
                    if ":" in line:
                        k, _, v = line.partition(":")
                        frontmatter[k.strip()] = v.strip()
                content = parts[2]

        complexity = frontmatter.get("complexity", "Unknown")

        prompt_no_spec = ""
        if "## Prompt" in content:
            after_prompt = content.split("## Prompt", 1)[1]
            if "## Specification" in after_prompt:
                prompt_no_spec = after_prompt.split("## Specification", 1)[0].strip()
            else:
                prompt_no_spec = after_prompt.strip()

        if not prompt_no_spec:
            prompt_no_spec = content.strip()

        prompt_with_spec = content.strip()
        return prompt_no_spec, prompt_with_spec, complexity

    def load_all(self) -> List[BenchmarkItem]:
        """Carrega todos os itens de benchmarks das pastas 'data/' e 'benchmarks/'."""
        items: List[BenchmarkItem] = []

        # 1. Carrega de arquivos JSON na pasta data/
        if self.data_dir.exists():
            for json_file in sorted(self.data_dir.glob("*.json")):
                benchmark_default = json_file.stem.lower()
                try:
                    with open(json_file, "r", encoding="utf-8") as f:
                        content = json.load(f)
                        data_list = content if isinstance(content, list) else [content]
                        for raw_item in data_list:
                            normalized = self._normalize_dict(raw_item, benchmark_default)
                            # skip multimodal items with no image — prompt is meaningless without screenshot
                            if normalized.get("multimodal") and not normalized.get("image_path"):
                                continue
                            items.append(BenchmarkItem(**normalized))
                except Exception as err:
                    print(f"Erro ao processar o arquivo {json_file.name}: {err}")

        # 2. Carrega de arquivos Markdown na pasta benchmarks/
        if self.benchmarks_dir.exists():
            for md_file in sorted(self.benchmarks_dir.rglob("*.md")):
                if md_file.name.startswith("_template"):
                    continue
                try:
                    text = md_file.read_text(encoding="utf-8")
                    item_id = md_file.stem

                    benchmark_name = md_file.parent.parent.name if md_file.parent.parent != self.benchmarks_dir else md_file.parent.name

                    prompt_no_spec, prompt_with_spec, complexity = self._parse_markdown_benchmark(text)

                    # auto-detect collocated image (e.g. db_easy_001.png alongside db_easy_001.md)
                    image_path: Optional[str] = None
                    for ext in (".png", ".jpg", ".jpeg", ".webp"):
                        candidate = md_file.with_suffix(ext)
                        if candidate.exists():
                            image_path = str(candidate)
                            break

                    items.append(BenchmarkItem(
                        id=item_id,
                        benchmark_name=benchmark_name,
                        prompt_no_spec=prompt_no_spec,
                        prompt_with_spec=prompt_with_spec,
                        complexity=complexity,
                        source="custom",
                        multimodal=image_path is not None,
                        image_path=image_path,
                    ))
                except Exception as err:
                    print(f"Erro ao processar Markdown {md_file.name}: {err}")

        return items

    def load(self, path=None) -> List[BenchmarkItem]:
        """Alias de compatibilidade para chamadas do tipo loader.load()."""
        return self.load_all()


# Alias para retrocompatibilidade
BenchmarkLoader = BenchmarkDataLoader