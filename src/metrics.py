from typing import List, Dict, Any
import pandas as pd

try:
    from .models import EvalResult
except ImportError:
    from models import EvalResult


class MetricsEngine:
    def __init__(self, results: List[EvalResult]) -> None:
        self.results = results
        raw_list = [
            r.model_dump() if hasattr(r, "model_dump") else r.dict()
            for r in results
        ] if results else []
        self._df = pd.DataFrame(raw_list) if raw_list else pd.DataFrame()

    def win_rate_spec_vs_no_spec(self) -> float:
        if self._df.empty or "visual_score" not in self._df.columns:
            return 0.0

        pivot = self._df.pivot_table(
            index="item_id",
            columns="prompt_type",
            values="visual_score",
            aggfunc="first",
        )

        if "With_Spec" not in pivot.columns or "No_Spec" not in pivot.columns:
            return 0.0

        paired = pivot.dropna(subset=["With_Spec", "No_Spec"])
        if paired.empty:
            return 0.0

        wins = int((paired["With_Spec"] > paired["No_Spec"]).sum())
        return wins / len(paired)

    def summary(self) -> Dict[str, Any]:
        if self._df.empty:
            return {}

        return {
            "total_evaluations": len(self._df),
            "spec_win_rate": self.win_rate_spec_vs_no_spec(),
            "avg_visual_score": float(self._df["visual_score"].mean()),
            "avg_visual_score_by_type": self._df.groupby("prompt_type")["visual_score"].mean().to_dict(),
            "execution_success_rate": float(self._df["execution_success"].mean()),
        }