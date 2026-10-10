"""Qualidade de código sobre o CSS REAL do Tailwind 4 no Chrome (lento): pytest -m slow

Confere à mão os números de uma página pequena, o que também valida a leitura do tema
(`var(--spacing)`), das camadas e das media queries `(min-width: 48rem)` / `not (min-width: ...)`.
"""

import os
import shutil
from pathlib import Path

import pytest

from specui.codegen import parse_bundle
from specui.harness import BrowserSession, ScaffoldHarness, StaticServer
from specui.metrics.code_quality import compute_code_quality

pytestmark = pytest.mark.slow

if not shutil.which("node"):  # pragma: no cover
    pytest.skip("Node não encontrado", allow_module_level=True)

PAGE = (
    "```ts file=src/app/app.ts\nimport { Component } from '@angular/core';\n"
    "@Component({selector: 'app-root', templateUrl: './app.html', styleUrl: './app.css'})\nexport class App {}\n```\n"
    '```html file=src/app/app.html\n<header class="p-4 md:p-8 lg:w-[500px] max-sm:hidden"><h1 class="btn text-2xl">Oi</h1>'
    '<div class="grid grid-cols-2 gap-4 mx-auto w-[123px] absolute top-2" style="color:red">'
    '<span class="btn">a</span><p class="min-h-screen">b</p></div></header>\n```\n'
    "```css file=src/app/app.css\n.card { padding: 10px; margin: 1rem 2px; width: 50%; }\n```\n"
    "```css file=src/styles.css\n.btn { border-radius: 4px; padding: 0 12px; }\n"
    "@media (min-width: 700px) { .btn { margin-left: 2rem; } }\n```\n"
)


def test_real_tailwind_page_matches_hand_computed_values(repo_root, tmp_path):
    ws = Path(os.environ.get("SPECUI_TEST_WORKSPACE", "C:/specui-work-test"))
    harness = ScaffoldHarness(repo_root / "scaffold" / "angular-base", ws, 240)
    run_dir = harness.prepare_run_dir("t-cq")
    try:
        harness.inject(parse_bundle(PAGE), run_dir)
        build = harness.build(run_dir)
        assert build.ok, build.error_messages
        with StaticServer(build.dist_dir) as server, BrowserSession() as session:
            art = session.capture_initial_render(server.url, (1440, 900), tmp_path)
    finally:
        harness.cleanup(run_dir)

    m = compute_code_quality(art.css_snapshot)
    c = m.counts
    # elementos (sem app-root): header, h1, div, span, p
    assert c["elements_total"] == 5
    assert m.str_ == pytest.approx(3 / 5)  # header, h1, p
    assert m.isr == pytest.approx(1 / 5)  # o div com style=""
    assert (c["positioned_absolute"], c["positioned_total"]) == (1, 1) and m.apr == 1.0
    assert (c["containers_flex_grid"], c["containers_total"]) == (1, 2)  # só o div é grid; header é block
    assert (c["arbitrary_classes"], c["classes_total"]) == (2, 15)  # w-[123px] e lg:w-[500px]
    # layout: relativos = p-4, md:p-8, gap-4, top-2, min-h-screen, grid-cols-2 (6, via tema) + .btn margin 2rem
    #         + .card margin 1rem + .card width 50%; absolutos = 123px, 500px, .btn padding 12px,
    #         .card padding 10px, .card margin 2px
    assert (c["layout_declarations_relative"], c["layout_declarations_total"]) == (9, 14)
    assert m.rur == pytest.approx(9 / 14)
    # faixas: max-sm (S), md (M), lg (L) e a media do .btn em 700px (M); nenhuma de XL
    assert (c["bands_covered"], c["bands_total"]) == (3, 4) and m.bc == pytest.approx(0.75)
    # .btn (global do modelo) usada 2x; .card (componente) definida e nunca usada
    assert (c["custom_classes_used"], c["custom_classes_reused"], c["custom_classes_dead"]) == (1, 1, 1)
    assert m.ccr == 1.0
