import os
import re
from typing import Optional

try:
    from google import genai
    USING_GENAI_SDK = True
except ImportError:
    USING_GENAI_SDK = False


class CodeGenerator:
    def __init__(self, model_name: Optional[str] = None):
        self.api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            keys = os.getenv("GEMINI_API_KEYS", "").split(",")
            if keys and keys[0].strip():
                self.api_key = keys[0].strip()

        self.requested_model = model_name
        self.model_name = self._discover_and_validate_model()

    def _discover_and_validate_model(self) -> str:
        """Lista os modelos da API e seleciona um modelo 'flash' ativo."""
        if not (USING_GENAI_SDK and self.api_key):
            return "gemini-2.5-flash"

        client = genai.Client(api_key=self.api_key)
        
        discovered_models = []
        try:
            for m in client.models.list():
                name = m.name.replace("models/", "")
                discovered_models.append(name)
        except Exception:
            pass

        flash_candidates = [m for m in discovered_models if "flash" in m.lower()]
        other_candidates = [m for m in discovered_models if m not in flash_candidates]
        candidates = flash_candidates + other_candidates

        if not candidates:
            candidates = ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-2.0-flash"]

        for cand in candidates:
            try:
                client.models.generate_content(model=cand, contents="Ping")
                return cand
            except Exception:
                continue

        return "gemini-2.5-flash"

    def generate_code(self, prompt: str, item_id: str = "") -> str:
        """Gera o código HTML completo baseado nas instruções do prompt."""
        system_instruction = (
            "Você é um desenvolvedor Frontend especialista.\n"
            "Sua tarefa é gerar um código HTML5 completo, moderno e estilizado com base nos requisitos fornecidos.\n"
            "INSTRUÇÃO CRÍTICA: Retorne APENAS o código HTML puro dentro de um bloco de código ```html ... ``` sem qualquer texto explicativo antes ou depois."
        )

        full_prompt = f"{system_instruction}\n\nREQUISITOS DA INTERFACE:\n{prompt}"

        if not (USING_GENAI_SDK and self.api_key):
            return self._fallback_html(item_id)

        try:
            client = genai.Client(api_key=self.api_key)
            response = client.models.generate_content(
                model=self.model_name,
                contents=full_prompt
            )
            text = response.text or ""
            match = re.search(r"```html\s*(.*?)\s*```", text, re.DOTALL)
            if match:
                return match.group(1).strip()
            return text.strip()
        except Exception as e:
            print(f"   Falha na geração de código ({self.model_name}): {e}")

        return self._fallback_html(item_id)

    def _fallback_html(self, item_id: str) -> str:
        return (
            "<!DOCTYPE html>\n<html lang='pt-BR'>\n<head>\n"
            "<meta charset='UTF-8'>\n"
            "<script src='https://cdn.tailwindcss.com'></script>\n</head>\n"
            "<body class='bg-gray-100 flex items-center justify-center h-screen'>\n"
            f"<div class='p-8 bg-white rounded-lg shadow-md'>\n<h1 class='text-2xl font-bold text-red-600'>Interface: {item_id}</h1>\n"
            "<p class='text-gray-600 mt-2'>Falha na geração automática de código pela API.</p>\n"
            "</div>\n</body>\n</html>"
        )