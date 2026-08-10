# check_models.py
import os
from dotenv import load_dotenv
from google import genai

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

if not api_key:
    print("API Key não encontrada no arquivo .env!")
    exit(1)

client = genai.Client(api_key=api_key)
print("Consultando modelos ativos na sua chave de API...\n")

try:
    for m in client.models.list():
        # Exibe apenas modelos que suportam geração de texto/visão
        print(f"• Name: {m.name}")
except Exception as e:
    print(f"Erro ao listar modelos: {e}")