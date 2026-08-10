from typing import List, Literal, Optional, Dict, Any
from pydantic import BaseModel, Field


class BenchmarkItem(BaseModel):
    id: str
    benchmark_name: str
    prompt_no_spec: str
    prompt_with_spec: str
    multimodal: bool = False
    image_path: Optional[str] = None
    spec_details: Optional[Dict[str, Any]] = None


class EvalResult(BaseModel):
    item_id: str
    benchmark_name: Optional[str] = None
    prompt_type: Literal["No_Spec", "With_Spec"]
    raw_code: str
    has_html_syntax_error: bool
    js_console_errors: List[str] = Field(default_factory=list)
    execution_success: bool
    execution_time_ms: float
    artifact_path: Optional[str] = None
    screenshot_path: Optional[str] = None
    visual_score: float = 0.0
    visual_verdict: Optional[str] = None
    visual_feedback: Optional[Dict[str, Any]] = None
    feedback: Optional[str] = None


class RunConfig(BaseModel):
    provider: str = "google"
    model: str = "gemini-2.5-flash"
    benchmarks_dir: str = "benchmarks"
    results_dir: str = "results"
    mock_mode: bool = False
    temperature: float = 0.2
    max_tokens: int = 4096
    output_dir: str = "results"
    gemini_request_delay_s: float = 3.0
    gemini_max_retries: int = 4