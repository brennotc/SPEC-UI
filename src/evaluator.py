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
            raise ValueError("Nenhuma GEMINI_API_KEY configurada no arquivo .env para o Evaluator!")

        self.screenshots_dir = Path("results") / "screenshots"
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

        self.model_name = self._discover_and_validate_model()

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
                inputs = page.query_selector_all("input[type='text'], input[type='email'], textarea")
                links = page.query_selector_all("a[href]")

                total_interactive = len(buttons) + len(inputs) + len(links)
                e2e_report["interactive_elements"] = total_interactive

                interactions_passed = 0
                for inp in inputs[:3]:
                    try:
                        if inp.is_visible() and inp.is_enabled():
                            inp.fill("Teste E2E")
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

    def _parse_judge_json(self, raw_text: str) -> Dict[str, Any]:
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = cleaned.strip()

        try:
            return json.loads(cleaned)
        except Exception:
            pass

        try:
            sanitized = cleaned.replace("\n", " ").replace("\r", " ")
            return json.loads(sanitized)
        except Exception:
            pass

        extracted = {}
        for key in ["layout_score", "design_score", "requirements_score", "total_score"]:
            match = re.search(rf'"{key}"\s*:\s*(\d+)', cleaned)
            if match:
                extracted[key] = int(match.group(1))

        v_match = re.search(r'"verdict"\s*:\s*"([^"]+)"', cleaned, re.IGNORECASE)
        if v_match:
            extracted["verdict"] = v_match.group(1).upper()

        f_match = re.search(r'"feedback"\s*:\s*"([^"]+)"', cleaned)
        if f_match:
            extracted["feedback"] = f_match.group(1)
        else:
            extracted["feedback"] = "Avaliação parcial efetuada com sucesso via extrator de emergência."

        if "total_score" not in extracted:
            l = extracted.get("layout_score", 20)
            d = extracted.get("design_score", 15)
            r = extracted.get("requirements_score", 15)
            extracted["total_score"] = l + d + r

        if "verdict" not in extracted:
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
        system_prompt = (
            "Você é um auditor sênior de Frontend e UI/UX.\n"
            "Avalie a interface fornecida de 0 a 100 com base nestes critérios:\n"
            "- Layout e Alinhamento (0-40 pts)\n"
            "- Estilo e Cores (0-30 pts)\n"
            "- Requisitos Solicitados (0-30 pts)\n\n"
            "FORMATO DE RESPOSTA OBRIGATÓRIO EM JSON:\n"
            "{\n"
            '  "layout_score": 30,\n'
            '  "design_score": 20,\n'
            '  "requirements_score": 20,\n'
            '  "total_score": 70,\n'
            '  "verdict": "PASS",\n'
            '  "feedback": "Interface limpa e bem alinhada."\n'
            "}"
        )

        prompt_original = item.prompt_with_spec if prompt_type == "With_Spec" else item.prompt_no_spec
        contents = [system_prompt]

        if item.image_path and Path(item.image_path).is_file():
            try:
                with open(item.image_path, "rb") as f:
                    ref_bytes = f.read()
                contents.append("[GABARITO ORIGINAL DO BENCHMARK]:")
                contents.append(types.Part.from_bytes(data=ref_bytes, mime_type="image/png"))
            except Exception:
                pass

        if screenshot_path and screenshot_path.is_file():
            try:
                with open(screenshot_path, "rb") as f:
                    shot_bytes = f.read()
                contents.append("📸 [SCREENSHOT RENDERIZADO DA INTERFACE GERADA]:")
                contents.append(types.Part.from_bytes(data=shot_bytes, mime_type="image/png"))
            except Exception:
                pass
        else:
            contents.append(f"Código HTML:\n```html\n{generated_code[:2000]}\n```")

        contents.append(
            f"TAREFA: {item.id} ({item.benchmark_name})\n"
            f"VARIAÇÃO: {prompt_type}\n"
            f"REQUISITOS DO BENCHMARK:\n\"{prompt_original}\"\n\n"
            "Compare a interface com os requisitos acima e retorne o JSON de avaliação:"
        )

        client = genai.Client(api_key=self.api_key)
        config = types.GenerateContentConfig(
            temperature=0.1,
            max_output_tokens=2048,
            response_mime_type="application/json"
        )

        try:
            response = client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=config
            )
            raw_text = (response.text or "").strip()
            
            data = self._parse_judge_json(raw_text)

            score = int(data.get("total_score", 50))
            verdict = "PASS" if score >= 70 else "FAIL"
            feedback = str(data.get("feedback", "Avaliação concluída."))
            
            print(f"      Breakdown -> Layout: {data.get('layout_score', '?')}/40 | Design: {data.get('design_score', '?')}/30 | Req: {data.get('requirements_score', '?')}/30")
            return score, verdict, feedback, data

        except Exception as err:
            print(f"      Erro inesperado na API do Juiz Visual ({self.model_name}): {err}")

        fallback_dict = {
            "layout_score": 20, "design_score": 15, "requirements_score": 15,
            "total_score": 50, "verdict": "FAIL", "feedback": "Falha no processamento do Juiz Visual."
        }
        return 50, "FAIL", "Falha na resposta do Juiz Visual.", fallback_dict