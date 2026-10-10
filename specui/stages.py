"""Estágios de métrica: cada um recebe o StageContext e preenche campos do RunRecord.

Os estágios são agrupados (technical, visual, ...) para `specui evaluate --groups`, que recalcula
métricas a partir dos artefatos já gravados (screenshot, dom_blocks.json, css_snapshot.json),
SEM chamar o LLM nem refazer o build.
"""

import json
import logging
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from specui.codegen import GeneratedBundle
from specui.harness import BrowserSession, BuildResult, RenderArtifacts, StaticServer
from specui.metrics import embeddings as emb
from specui.metrics.code_quality import compute_code_quality
from specui.metrics.design2code import (
    blocks_from_dom,
    blocks_from_ref,
    compute_design2code,
    inpaint_text,
    with_boxes,
    write_pairs,
)
from specui.metrics.functional import compute_functional
from specui.metrics.pixel import load_rgb, mae, ssim
from specui.metrics.reference import ReferenceUnavailableError, load_reference_blocks
from specui.metrics.technical import compute_technical
from specui.models import Cell, EmbeddingMetrics, PromptPackage, RunConfig, RunRecord, Task
from specui.oracle import load_suite, run_suite
from specui.oracle.provenance import read_provenance
from specui.oracle.requirements import load_requirements

logger = logging.getLogger(__name__)


@dataclass
class StageContext:
    """Tudo o que um estágio pode precisar. `cell`, `pkg`, `bundle`, `build` e `url` são None
    quando o contexto vem do disco (`evaluate`); os estágios não podem depender deles, a menos
    que tratem a ausência."""

    cfg: RunConfig
    task: Task
    render: RenderArtifacts
    out_dir: Path
    record: RunRecord
    cell: Cell | None = None
    pkg: PromptPackage | None = None
    bundle: GeneratedBundle | None = None
    build: BuildResult | None = None
    url: str | None = None  # servidor estático do dist (só enquanto o app está no ar)
    session: BrowserSession | None = None


MetricStage = Callable[[StageContext], None]


def _note(ctx: StageContext, message: str) -> None:
    """Aviso informativo (não é falha: a métrica fica None com o motivo registrado)."""
    if message not in ctx.record.errors:
        ctx.record.errors.append(message)


# ----------------------------------------------------------------------------- estágios


def stage_technical(ctx: StageContext) -> None:
    ctx.record.technical = compute_technical(ctx.render)


def stage_design2code(ctx: StageContext) -> None:
    """Block-Match, Text, Position e Color contra os blocos do design do Figma."""
    try:
        refs, source = load_reference_blocks(
            ctx.task, ctx.cfg.path("references_dir"), ctx.cfg.enable_ocr_fallback
        )
    except ReferenceUnavailableError as exc:
        _note(ctx, f"design2code: referência indisponível ({exc})")
        return
    metrics, details = compute_design2code(refs, ctx.render.dom_blocks, ctx.render.viewport, source)
    metrics.pairs_path = write_pairs(ctx.out_dir / "pairs.json", details)
    previous = ctx.record.design2code
    if previous is not None:  # reavaliação só do grupo visual: preserva o CLIP já calculado
        metrics.clip_inpainted = previous.clip_inpainted
    ctx.record.design2code = metrics


def _embeddings_record(ctx: StageContext) -> EmbeddingMetrics:
    if ctx.record.embeddings is None:
        ctx.record.embeddings = EmbeddingMetrics()
    return ctx.record.embeddings


def stage_pixel(ctx: StageContext) -> None:
    """MAE (Figma2Code) e SSIM (secundária) entre o render e o design."""
    shot = ctx.out_dir / "screenshot.png"
    record = _embeddings_record(ctx)
    record.mae = mae(shot, ctx.task.image_path)
    record.ssim = ssim(shot, ctx.task.image_path)


def stage_embeddings(ctx: StageContext) -> None:
    """VES (DINOv2) e CLIP com o texto removido. Sem torch/transformers: None + motivo."""
    if not ctx.cfg.enable_embeddings:
        return
    available, why = emb.embeddings_available()
    if not available:
        _note(ctx, f"embeddings desativados: {why}")
        return
    cache = ctx.cfg.model_cache_dir
    shot, design = ctx.out_dir / "screenshot.png", ctx.task.image_path
    _embeddings_record(ctx).ves_dinov2 = emb.ves_dinov2(shot, design, cache)

    if ctx.record.design2code is None:  # sem blocos de referência não há o que apagar
        return
    refs, _ = load_reference_blocks(ctx.task, ctx.cfg.path("references_dir"), ctx.cfg.enable_ocr_fallback)
    design_img = load_rgb(design)
    size = (design_img.shape[1], design_img.shape[0])
    to_u8 = lambda a: np.clip(np.rint(a * 255), 0, 255).astype("uint8")
    clean_design = inpaint_text(to_u8(design_img), with_boxes(blocks_from_ref(refs)))
    clean_render = inpaint_text(to_u8(load_rgb(shot, size=size)), with_boxes(blocks_from_dom(ctx.render.dom_blocks)))
    ctx.record.design2code.clip_inpainted = emb.clip_cosine(clean_render, clean_design, cache)


def stage_code_quality(ctx: StageContext) -> None:
    """RUR, APR, FU, BC, STR, AVU, ISR e CCR (Figma2Code) sobre o DOM e o CSS renderizados."""
    if not ctx.render.css_snapshot.get("elements"):
        _note(ctx, "code_quality: css_snapshot ausente ou vazio")
        return
    ctx.record.code_quality = compute_code_quality(ctx.render.css_snapshot)


def stage_functional(ctx: StageContext) -> None:
    """Nota funcional (WebGen-Bench): suíte Playwright determinística de `oracles/<tarefa>/`."""
    if ctx.url is None or ctx.session is None:
        _note(ctx, "functional: sem servidor/navegador para executar o oráculo")
        return
    oracles_dir = ctx.cfg.path("oracles_dir")
    suite = load_suite(oracles_dir, ctx.task.id)
    outcomes = run_suite(
        suite, ctx.session, ctx.url, ctx.render.viewport, levels=ctx.cfg.oracle_levels, block_network=ctx.cfg.block_network
    )
    requirements = {r.id: r for r in load_requirements(oracles_dir, ctx.task.id)}
    sha, tag = ctx.record.oracle_content_sha256, ctx.record.oracle_suite_tag
    if sha is None:  # reavaliação de um run sem proveniência gravada
        prov = read_provenance(ctx.cfg.repo_root, oracles_dir)
        sha, tag = prov.content_sha256, prov.tag
    ctx.record.functional = compute_functional(
        outcomes, requirements, ctx.record.material_shown, suite_sha256=sha, suite_git_tag=tag
    )


STAGE_GROUPS: dict[str, list[MetricStage]] = {
    "technical": [stage_technical],
    "visual": [stage_design2code, stage_pixel, stage_embeddings],
    "code": [stage_code_quality],
    "functional": [stage_functional],
}


def default_stages(cfg: RunConfig | None = None, groups: Sequence[str] | None = None) -> list[MetricStage]:
    """Estágios na ordem de execução, filtrados por grupo (padrão: todos)."""
    names = list(groups) if groups else list(STAGE_GROUPS)
    unknown = set(names) - set(STAGE_GROUPS)
    if unknown:
        raise ValueError(f"grupos de métrica desconhecidos: {sorted(unknown)} (existem: {sorted(STAGE_GROUPS)})")
    return [stage for name in STAGE_GROUPS if name in names for stage in STAGE_GROUPS[name]]


def run_stages(ctx: StageContext, stages: Sequence[MetricStage]) -> list[str]:
    """Executa os estágios; uma métrica quebrada vira `metric_error` e não derruba o resto.
    Devolve os nomes dos estágios que falharam."""
    failed: list[str] = []
    for stage in stages:
        try:
            stage(ctx)
        except Exception as exc:
            logger.exception("estágio %s falhou em %s", stage.__name__, ctx.record.run_id)
            failed.append(stage.__name__)
            ctx.record.status = "metric_error"
            ctx.record.errors.append(f"{stage.__name__}: {type(exc).__name__}: {exc}")
    return failed


# ----------------------------------------------------------------------------- reavaliação


def render_from_disk(rec: RunRecord, run_dir: Path, viewport: tuple[int, int]) -> RenderArtifacts:
    """RenderArtifacts reconstruído dos arquivos gravados (sem navegador)."""

    def load(key: str) -> Any:
        name = rec.paths.get(key)
        path = run_dir / name if name else None
        return json.loads(path.read_text(encoding="utf-8")) if path and path.is_file() else None

    tech = rec.technical
    return RenderArtifacts(
        render_ok=bool(rec.exec.render_ok),
        viewport=viewport,
        screenshot_path=str(run_dir / rec.paths["screenshot"]) if "screenshot" in rec.paths else None,
        console_errors=list(tech.console_errors) if tech else [],
        blocked_requests=list(tech.blocked_requests) if tech else [],
        axe_violations=dict(tech.axe_violations) if tech else {},
        axe_path=str(run_dir / rec.paths["axe"]) if "axe" in rec.paths else None,
        dom_blocks=load("dom_blocks") or [],
        css_snapshot=load("css_snapshot") or {},
    )


def reevaluate_record(
    cfg: RunConfig, run_root: Path, rec: RunRecord, task: Task, groups: Sequence[str] | None = None,
    session: BrowserSession | None = None,
) -> RunRecord:
    """Recalcula as métricas dos grupos pedidos de uma execução já gravada.

    Só vale para execuções que renderizaram (`done` ou `metric_error`); as demais não têm
    screenshot nem DOM. `run_root` é a raiz dos resultados (results/ ou results/pilot/).
    """
    if rec.status not in ("done", "metric_error"):
        raise ValueError(f"{rec.run_id}: status '{rec.status}' não tem render para reavaliar")
    stages = default_stages(cfg, groups)
    out_dir = run_root / rec.paths["run_dir"]
    viewport = cfg.viewport or task.image_size
    render = render_from_disk(rec, out_dir, viewport)

    rec.paths["run_dir"] = str(out_dir)  # absoluto enquanto os estágios gravam; relativizado no fim
    names = tuple(f"{s.__name__}:" for s in stages)
    rec.errors = [e for e in rec.errors if not e.startswith(names)]  # erros antigos desses estágios
    ctx = StageContext(cfg=cfg, task=task, render=render, out_dir=out_dir, record=rec)
    dist = out_dir / rec.paths["dist_dir"] if "dist_dir" in rec.paths else None
    with ExitStack() as stack:
        if stage_functional in stages and session is not None and dist is not None and dist.is_dir():
            ctx.url = stack.enter_context(StaticServer(dist)).url  # o oráculo precisa do app no ar
            ctx.session = session
        failed = run_stages(ctx, stages)
    if not failed and rec.status == "metric_error":
        still_broken = any(e.split(":", 1)[0].startswith("stage_") for e in rec.errors)
        rec.status = "metric_error" if still_broken else "done"
    # os caminhos novos (pairs.json) voltam relativos, como no pipeline
    from specui.pipeline import _relativize_paths

    _relativize_paths(rec, run_root)
    return rec
