import os
import json
import re
import time
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

try:
    from google import genai
    from google.genai import types
    USING_GENAI_SDK = True
except ImportError:
    USING_GENAI_SDK = False

try:
    from .models import BenchmarkItem, EvalResult
except ImportError:
    from models import BenchmarkItem, EvalResult


class CodeEvaluator:
    def __init__(self, model_name: Optional[str] = None, provider: str = "gemini"):
        self.provider = provider
        self.requested_model = model_name
        
        self.api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            keys = os.getenv("GEMINI_API_KEYS", "").split(",")
            if keys and keys[0].strip():
                self.api_key = keys[0].strip()

        if not self.api_key:
            raise ValueError("Nenhuma GEMINI_API_KEY configurada no ambiente para o Evaluator!")

        self.screenshots_dir = Path("results") / "screenshots"
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

        self.model_name = self._discover_and_validate_model()
        self._seen_feedbacks: List[str] = []

    def _discover_and_validate_model(self) -> str:
        if not USING_GENAI_SDK:
            return "gemini-pro-latest"

        client = genai.Client(api_key=self.api_key)
        
        discovered_models = []
        try:
            for m in client.models.list():
                name = m.name.replace("models/", "")
                discovered_models.append(name)
        except Exception:
            pass

        pro_candidates = [m for m in discovered_models if "pro" in m.lower()]
        other_candidates = [m for m in discovered_models if m not in pro_candidates]
        candidates = pro_candidates + other_candidates

        if not candidates:
            candidates = ["gemini-pro-latest", "gemini-2.5-pro", "gemini-1.5-pro"]

        for cand in candidates:
            try:
                client.models.generate_content(model=cand, contents="Ping")
                return cand
            except Exception:
                continue

        return "gemini-pro-latest"

    def _clean_spec_for_judge(self, full_spec_text: str) -> str:
        text = full_spec_text
        for header in ["# 6. CRITÉRIOS DE VERIFICAÇÃO E TESTES", "## 6. CRITÉRIOS DE VERIFICAÇÃO", "CRITÉRIOS DE VERIFICAÇÃO E TESTES"]:
            if header in text:
                text = text.split(header)[0]

        text = re.sub(r'```typescript.*?```', '[Contrato TypeScript omitido]', text, flags=re.DOTALL)
        return text.strip()

    def _sanitize_and_fix_html(self, html_code: str) -> str:
        """Repara HTML/JS truncado para evitar quebras no Playwright."""
        code = html_code.strip()
        
        open_scripts = len(re.findall(r'<script', code, re.IGNORECASE))
        close_scripts = len(re.findall(r'</script>', code, re.IGNORECASE))
        if open_scripts > close_scripts:
            code += "\n</script>"

        if "</body>" not in code.lower():
            code += "\n</body>"
        if "</html>" not in code.lower():
            code += "\n</html>"

        return code

    def _run_e2e_and_screenshot(self, html_path: Path, output_png_path: Path) -> Dict[str, Any]:
        e2e_report = {
            "success": False,
            "js_errors": [],
            "interactive_elements": 0,
            "interactions_passed": 0,
            "functional_score": 0.0,
            "has_screenshot": False
        }

        if not PLAYWRIGHT_AVAILABLE:
            return e2e_report

        try:
            raw_content = html_path.read_text(encoding="utf-8")
            fixed_content = self._sanitize_and_fix_html(raw_content)
            html_path.write_text(fixed_content, encoding="utf-8")
        except Exception:
            pass

        js_errors: List[str] = []

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1280, "height": 800})
                page.on("pageerror", lambda err: js_errors.append(str(err)))

                file_url = html_path.resolve().as_uri()
                page.goto(file_url, wait_until="networkidle", timeout=12000)
                time.sleep(1.5)

                buttons = page.query_selector_all("button, input[type='button'], input[type='submit']")
                inputs = page.query_selector_all("input[type='text'], input[type='email'], textarea, input[type='number']")
                links = page.query_selector_all("a[href]")

                total_interactive = len(buttons) + len(inputs) + len(links)
                e2e_report["interactive_elements"] = total_interactive

                interactions_passed = 0
                for inp in inputs[:3]:
                    try:
                        if inp.is_visible() and inp.is_enabled():
                            inp.fill("10")
                            interactions_passed += 1
                    except Exception:
                        pass

                for btn in buttons[:3]:
                    try:
                        if btn.is_visible() and btn.is_enabled():
                            btn.click(timeout=1000)
                            interactions_passed += 1
                    except Exception:
                        pass

                e2e_report["interactions_passed"] = interactions_passed
                base_score = 100.0 - (len(js_errors) * 30)
                if total_interactive > 0 and interactions_passed == 0:
                    base_score -= 20.0

                e2e_report["functional_score"] = max(0.0, min(100.0, base_score))
                e2e_report["js_errors"] = js_errors
                page.screenshot(path=str(output_png_path), full_page=True)
                e2e_report["has_screenshot"] = True
                e2e_report["success"] = True
                browser.close()

        except Exception as e:
            e2e_report["js_errors"].append(f"Falha Playwright: {str(e)}")

        return e2e_report

    def _parse_judge_json(self, raw_text: str) -> Dict[str, Any]:
        """Extrai e repara dados de JSON do Juiz com múltiplos fallbacks."""
        cleaned = raw_text.strip()
        
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = cleaned.strip()

        # 1. Parse direto
        try:
            return json.loads(cleaned)
        except Exception:
            pass

        # 2. Tenta fechar aspas e chaves truncadas
        try:
            repaired = cleaned
            if not repaired.endswith("}"):
                if not repaired.endswith('"'):
                    repaired += '"'
                repaired += '}'
            return json.loads(repaired)
        except Exception:
            pass

        # 3. Extração via Regex
        extracted = {}
        for key in ["layout_score", "design_score", "requirements_score", "total_score"]:
            match = re.search(rf'"{key}"\s*:\s*(\d+)', cleaned)
            if match:
                extracted[key] = int(match.group(1))

        v_match = re.search(r'"verdict"\s*:\s*"([^"]+)"', cleaned, re.IGNORECASE)
        if v_match:
            extracted["verdict"] = v_match.group(1).strip()

        f_match = re.search(r'"feedback"\s*:\s*"((?:[^"\\]|\\.)*)"', cleaned, re.DOTALL)
        if f_match:
            extracted["feedback"] = f_match.group(1).replace('\\"', '"').replace('\n', ' ').strip()
        else:
            extracted["feedback"] = cleaned[:300].replace('\n', ' ')

        if "total_score" not in extracted:
            extracted["total_score"] = (
                extracted.get("layout_score", 0) + 
                extracted.get("design_score", 0) + 
                extracted.get("requirements_score", 0)
            )

        extracted["verdict"] = "PASS" if extracted.get("total_score", 0) >= 70 else "FAIL"
        return extracted

    def _run_visual_judge(
        self, 
        item: BenchmarkItem, 
        prompt_type: str,
        screenshot_path: Optional[Path], 
        generated_code: str,
        e2e_report: Dict[str, Any]
    ) -> Tuple[int, str, str, Dict[str, Any]]:
        """Executa a avaliação do Juiz garantindo respostas completas e concisas."""
        
        system_prompt = (
            "Você é um auditor sênior de UI/UX.\n"
            "Sua função é avaliar a interface gerada em relação à ESPECIFICAÇÃO DE REFERÊNCIA.\n\n"
            "REGRAS CRÍTICAS DE CONCISÃO:\n"
            "- Responda ESTRITAMENTE em JSON válido.\n"
            "- O campo 'feedback' DEVE ser extremamente conciso: no máximo 2 a 3 frases (limite estrito de 250 caracteres).\n"
            "- Seja direto ao ponto sobre o que faltou ou acertou. NUNCA faça textos longos para não ser cortado.\n\n"
            "ESTRUTURA DO JSON:\n"
            "{\n"
            '  "layout_score": <0-40>,\n'
            '  "design_score": <0-30>,\n'
            '  "requirements_score": <0-30>,\n'
            '  "total_score": <0-100>,\n'
            '  "verdict": "PASS" ou "FAIL",\n'
            '  "feedback": "Crítica objetiva e curta em até 250 caracteres."\n'
            "}"
        )

        ground_truth_spec = self._clean_spec_for_judge(item.prompt_with_spec)
        contents = [system_prompt]

        if screenshot_path and screenshot_path.is_file():
            try:
                with open(screenshot_path, "rb") as f:
                    shot_bytes = f.read()
                contents.append("📸 [SCREENSHOT DA INTERFACE GERADA]:")
                contents.append(types.Part.from_bytes(data=shot_bytes, mime_type="image/png"))
            except Exception:
                contents.append(f"Código HTML:\n```html\n{generated_code[:2000]}\n```")
        else:
            contents.append(f"Código HTML:\n```html\n{generated_code[:2000]}\n```")

        contents.append(
            f"TAREFA: {item.id} ({item.benchmark_name}) | MODO: {prompt_type}\n\n"
            f"ESPECIFICAÇÃO DE REFERÊNCIA:\n\"\"\"\n{ground_truth_spec[:1500]}\n\"\"\"\n\n"
            "Avalie a interface e gere o JSON completo, mantendo o feedback conciso."
        )

        judge_schema = {
            "type": "OBJECT",
            "properties": {
                "layout_score": {"type": "INTEGER"},
                "design_score": {"type": "INTEGER"},
                "requirements_score": {"type": "INTEGER"},
                "total_score": {"type": "INTEGER"},
                "verdict": {"type": "STRING", "enum": ["PASS", "FAIL"]},
                "feedback": {"type": "STRING"}
            },
            "required": ["layout_score", "design_score", "requirements_score", "total_score", "verdict", "feedback"]
        }

        client = genai.Client(api_key=self.api_key)
        
        config = types.GenerateContentConfig(
            temperature=0.1,
            max_output_tokens=2048,
            response_mime_type="application/json",
            response_schema=judge_schema
        )

        try:
            response = client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=config
            )
            raw_text = (response.text or "").strip()
            data = self._parse_judge_json(raw_text)

            score = int(data.get("total_score", 0))
            verdict = "PASS" if score >= 70 else "FAIL"
            feedback = str(data.get("feedback", "Avaliação concluída.")).strip()

            if feedback and not feedback.endswith(('.', '!', '?')):
                feedback += "..."

            print(f"      Breakdown -> Layout: {data.get('layout_score', '?')}/40 | Design: {data.get('design_score', '?')}/30 | Req: {data.get('requirements_score', '?')}/30")
            return score, verdict, feedback, data

        except Exception as err:
            print(f"⚠️ Aviso: Juiz Visual falhou para {item.id} ({prompt_type}): {err}. Aplicando nota fallback.")
            fallback_score = int(e2e_report.get("functional_score", 0) * 0.5)
            fallback_dict = {
                "layout_score": 0,
                "design_score": 0,
                "requirements_score": 0,
                "total_score": fallback_score,
                "verdict": "FAIL",
                "feedback": f"Falha no processamento da crítica do Juiz: {str(err)}"
            }
            return fallback_score, "FAIL", fallback_dict["feedback"], fallback_dict

    def evaluate(
        self,
        item: BenchmarkItem,
        prompt_type: str,
        generated_code: str,
        artifact_path: Path
    ) -> EvalResult:
        start_time = time.time()
        screenshot_png_path = self.screenshots_dir / f"{item.id}_{prompt_type}.png"
        e2e = self._run_e2e_and_screenshot(artifact_path, screenshot_png_path)
        execution_time_ms = round((time.time() - start_time) * 1000, 2)

        visual_score, verdict, raw_feedback_text, feedback_dict = self._run_visual_judge(
            item=item,
            prompt_type=prompt_type,
            screenshot_path=screenshot_png_path if e2e["has_screenshot"] else None,
            generated_code=generated_code,
            e2e_report=e2e
        )

        full_feedback_str = f"[E2E: {e2e['functional_score']}/100 | Erros JS: {len(e2e['js_errors'])}] -> {raw_feedback_text}"
        
        feedback_dict["full_feedback"] = full_feedback_str
        feedback_dict["e2e_report"] = e2e

        return EvalResult(
            item_id=item.id,
            benchmark_name=item.benchmark_name,
            prompt_type=prompt_type,
            raw_code=generated_code,
            has_html_syntax_error=bool(e2e["js_errors"]),
            js_console_errors=e2e["js_errors"],
            execution_success=e2e["success"],
            execution_time_ms=execution_time_ms,
            artifact_path=str(artifact_path),
            screenshot_path=str(screenshot_png_path) if e2e["has_screenshot"] else None,
            visual_score=visual_score,
            visual_verdict=verdict,
            visual_feedback=feedback_dict,
            feedback=full_feedback_str
        )