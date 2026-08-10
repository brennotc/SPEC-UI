import time
from typing import List, Tuple

class GroqRateLimiter:
    """
    Gerenciador dinâmico de Rate Limit (Tokens por Minuto) para APIs com limitações estritas.
    Mantém uma janela deslizante de 60 segundos para evitar estouro de TPM.
    """
    def __init__(self, tpm_limit: int = 7500):
        # Define 7500 como teto de segurança (abaixo do limite rígido de 8000 TPM)
        self.tpm_limit = tpm_limit
        self.history: List[Tuple[float, int]] = []  # List de (timestamp, tokens_usados)

    def _clean_old_records(self, now: float):
        """Remove registros com mais de 60 segundos."""
        self.history = [(ts, tok) for ts, tok in self.history if now - ts < 60.0]

    def get_current_tpm(self, now: float) -> int:
        self._clean_old_records(now)
        return sum(tok for _, tok in self.history)

    def wait_if_needed(self, estimated_tokens: int = 3000):
        """Pausa a execução dinamicamente caso a requisição vá estourar a cota por minuto."""
        now = time.time()
        current_tpm = self.get_current_tpm(now)

        if current_tpm + estimated_tokens > self.tpm_limit:
            if self.history:
                # Descobre quando o registro mais antigo expira da janela de 60s
                oldest_ts = self.history[0][0]
                wait_time = max(1.0, 60.0 - (now - oldest_ts) + 0.5)
            else:
                wait_time = 10.0

            print(f"\n⏳ [RateLimiter] Uso atual: {current_tpm}/{self.tpm_limit} TPM. Pausando por {wait_time:.1f}s para liberar cota da API...")
            time.sleep(wait_time)
            
            # Recalcula após esperar
            now = time.time()
            self._clean_old_records(now)

    def record_usage(self, tokens_used: int):
        """Registra o consumo real informado pela API na resposta."""
        self.history.append((time.time(), tokens_used))