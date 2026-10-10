"""Build real do Angular com o scaffold (lento: usa Node). Rode com: pytest -m slow

O primeiro teste instala o node_modules compartilhado (npm ci, ~1 min); os demais reaproveitam.
Workspace de teste: SPECUI_TEST_WORKSPACE (padrão C:/specui-work-test).
"""

import os
import shutil
import subprocess
import urllib.request
from pathlib import Path

import pytest

from specui.codegen import parse_bundle
from specui.harness import ScaffoldHarness, StaticServer
from specui.llm import MockClient
from specui.models import Generator, PromptPackage

pytestmark = pytest.mark.slow

pytest.importorskip("pydantic")
if not shutil.which("node") or not shutil.which("npm"):  # pragma: no cover
    pytest.skip("Node/npm não encontrados", allow_module_level=True)


@pytest.fixture(scope="module")
def harness(repo_root) -> ScaffoldHarness:
    ws = Path(os.environ.get("SPECUI_TEST_WORKSPACE", "C:/specui-work-test"))
    h = ScaffoldHarness(repo_root / "scaffold" / "angular-base", ws, build_timeout_s=240)
    h.ensure_workspace()
    return h


def _bundle(variant: str):
    gen = Generator(provider="mock", model_id="m", mock_variant=variant)
    dummy = PromptPackage(system="s", user_text="u", modality="text", envelope_version="2",
                          envelope_sha256="e", prompt_sha256="p")
    return parse_bundle(MockClient(gen).generate(dummy, 1).text)


def _node_command_lines() -> str:
    """Linhas de comando dos processos node em execução (vazio se não der para consultar)."""
    if os.name != "nt" or not shutil.which("powershell"):
        return ""
    cmd = "Get-CimInstance Win32_Process -Filter \"name='node.exe'\" | ForEach-Object { $_.CommandLine }"
    out = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                         capture_output=True, text=True, check=False)
    return out.stdout


def test_pristine_scaffold_builds(harness):
    result = harness.verify_pristine()
    assert result.ok, result.error_messages
    assert result.time_s < 120


def test_mock_bundle_builds_serves_and_cleans_up(harness, tmp_path):
    run_dir = harness.prepare_run_dir("t-ok")
    try:
        written = harness.inject(_bundle("ok"), run_dir)
        assert "src/app/app.ts" in written
        result = harness.build(run_dir)
        assert result.ok, result.error_messages
        assert result.dist_dir and (Path(result.dist_dir) / "index.html").is_file()
        assert result.return_code == 0 and not result.timed_out
        # o dist roda de verdade num servidor estático (módulos ES com MIME correto)
        with StaticServer(result.dist_dir) as srv, urllib.request.urlopen(srv.url) as r:
            html = r.read().decode("utf-8")
        assert "<app-root>" in html and 'href="./"' in html
        paths = harness.collect(run_dir, tmp_path / "saida", result)
        assert (Path(paths["generated_dir"]) / "src" / "app" / "app.ts").is_file()
        assert (Path(paths["dist_dir"]) / "index.html").is_file()
        assert Path(paths["build_stdout"]).is_file()
    finally:
        harness.cleanup(run_dir)
    assert not run_dir.exists()
    assert (harness.workspace_dir / "shared" / "node_modules" / "@angular").is_dir()  # intacto


def test_broken_bundle_fails_with_messages(harness):
    run_dir = harness.prepare_run_dir("t-broken")
    try:
        harness.inject(_bundle("broken"), run_dir)
        result = harness.build(run_dir)
        assert not result.ok and result.dist_dir is None and not result.timed_out
        assert result.return_code not in (0, None)
        assert result.error_messages, "deve extrair ao menos uma mensagem de erro"
    finally:
        harness.cleanup(run_dir)


def test_tailwind_icons_and_local_font_build(harness, tmp_path):
    """A stack inteira do envelope funciona: Tailwind (inclusive valor arbitrário), ng-icons dos
    dois pacotes e fonte local via @fontsource."""
    files = (
        "```ts file=src/app/app.ts\n"
        "import { Component } from '@angular/core';\n"
        "import { NgIcon, provideIcons } from '@ng-icons/core';\n"
        "import { heroPlay } from '@ng-icons/heroicons/outline';\n"
        "import { lucideTimer } from '@ng-icons/lucide';\n"
        "@Component({selector: 'app-root', imports: [NgIcon], viewProviders: [provideIcons({heroPlay, lucideTimer})],\n"
        "  templateUrl: './app.html'})\nexport class App {}\n```\n"
        '```html file=src/app/app.html\n<div class="bg-red-500 w-[123px] text-white">'
        '<ng-icon name="heroPlay" /><ng-icon name="lucideTimer" /></div>\n```\n'
        '```css file=src/styles.css\n@import "@fontsource/inter/400.css";\nbody { font-family: "Inter"; }\n```\n'
    )
    run_dir = harness.prepare_run_dir("t-stack")
    try:
        harness.inject(parse_bundle(files), run_dir)
        result = harness.build(run_dir)
        assert result.ok, result.error_messages
        css = (Path(result.dist_dir) / "styles.css").read_text(encoding="utf-8")
        assert ".bg-red-500" in css and "width: 123px" in css and "@font-face" in css
        assert any((Path(result.dist_dir) / "media").glob("inter-*.woff2"))
    finally:
        harness.cleanup(run_dir)


def test_timeout_kills_the_whole_process_tree(repo_root):
    ws = Path(os.environ.get("SPECUI_TEST_WORKSPACE", "C:/specui-work-test"))
    quick = ScaffoldHarness(repo_root / "scaffold" / "angular-base", ws, build_timeout_s=1)
    run_dir = quick.prepare_run_dir("t-timeout")
    try:
        quick.inject(_bundle("ok"), run_dir)
        result = quick.build(run_dir)
        assert result.timed_out and not result.ok
        assert result.error_messages == ["timeout: build excedeu 1s"]
        assert result.time_s < 60
    finally:
        quick.cleanup(run_dir)
    # nenhum node órfão ficou rodando a partir do diretório apagado
    assert "t-timeout" not in _node_command_lines()
