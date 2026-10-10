"""Harness do scaffold e servidor estático: testes rápidos (sem Node)."""

import json
import os
import urllib.request

import pytest

from specui.codegen import parse_bundle
from specui.harness import ScaffoldHarness, StaticServer
from specui.harness.scaffold import extract_error_messages, make_dir_link, remove_dir_link
from specui.llm.base import ConfigurationError


@pytest.fixture
def harness(repo_root, tmp_path):
    return ScaffoldHarness(repo_root / "scaffold" / "angular-base", tmp_path / "ws")


def test_scaffold_info_is_pinned_and_complete(harness):
    info = harness.info()
    assert info.angular_version == "20.3.33"
    assert info.version == "1.0.0"
    assert len(info.lock_sha256) == 64 and len(info.tree_sha256) == 64
    for pkg in ("@angular/core", "@angular/forms", "@ng-icons/core", "@ng-icons/heroicons",
                "@ng-icons/lucide", "@fontsource/inter", "@fontsource/roboto", "@fontsource/poppins",
                "tailwindcss", "rxjs"):
        assert pkg in info.packages, pkg
    for hidden in ("tslib", "zone.js", "@angular/compiler"):
        assert hidden not in info.packages
    assert info.packages["tailwindcss"].startswith("4.")
    assert info.packages["@ng-icons/core"].startswith("32.")  # última série que aceita Angular 20


def test_scaffold_info_hashes_are_stable(harness):
    assert harness.info() == harness.info()


def test_unpinned_versions_are_rejected(repo_root, tmp_path):
    scaffold = tmp_path / "sc"
    scaffold.mkdir()
    (scaffold / "package.json").write_text(
        json.dumps({"dependencies": {"@angular/core": "^20.0.0"}}), encoding="utf-8")
    (scaffold / "package-lock.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="não fixadas"):
        ScaffoldHarness(scaffold, tmp_path / "ws").info()


def test_extract_error_messages_strips_ansi_and_dedupes():
    text = (
        "\x1b[31m✘ [ERROR]\x1b[0m TS2304: Cannot find name 'foo'. [plugin angular-compiler]\n\n"
        "    src/app/app.ts:3:10:\n"
        "✘ [ERROR] TS2304: Cannot find name 'foo'. [plugin angular-compiler]\n"
        "✘ [ERROR] NG8001: 'ng-icon' is not a known element\n"
        "Error: Something else\n"
    )
    assert extract_error_messages(text) == [
        "TS2304: Cannot find name 'foo'. [plugin angular-compiler]",
        "NG8001: 'ng-icon' is not a known element",
        "Error: Something else",
    ]
    assert extract_error_messages("tudo certo") == []


def test_inject_maps_styles_and_stays_inside_src(harness, tmp_path):
    run_dir = tmp_path / "run"
    (run_dir / "src").mkdir(parents=True)
    bundle = parse_bundle(
        "```ts file=src/app/app.ts\nexport class App {}\n```\n"
        "```css file=src/styles.css\nh1 { color: red; }\n```\n"
        "```html file=src/app/parts/x.html\n<p>x</p>\n```\n"
    )
    written = harness.inject(bundle, run_dir)
    assert written == ["src/app/app.ts", "src/app.styles.css", "src/app/parts/x.html"]
    assert (run_dir / "src" / "app.styles.css").read_text(encoding="utf-8") == "h1 { color: red; }\n"
    assert not (run_dir / "src" / "styles.css").exists()  # o styles.css fixo não é tocado
    # defesa em profundidade: um bundle forjado com caminho fora de src/ é recusado
    evil = bundle.model_copy(update={"files": [bundle.files[0].model_copy(update={"path": "../fora.ts"})]})
    with pytest.raises(ValueError, match="fora de src/"):
        harness.inject(evil, run_dir)


def test_cleanup_never_touches_the_linked_node_modules(harness, tmp_path):
    shared_modules = harness.workspace_dir / "shared" / "node_modules"
    shared_modules.mkdir(parents=True)
    (shared_modules / "pacote.txt").write_text("não apague", encoding="utf-8")
    run_dir = harness.workspace_dir / "run-x"
    run_dir.mkdir()
    (run_dir / "src.txt").write_text("x", encoding="utf-8")
    make_dir_link(run_dir / "node_modules", shared_modules)
    assert (run_dir / "node_modules" / "pacote.txt").is_file()  # o link funciona
    harness.cleanup(run_dir)
    assert not run_dir.exists()
    assert (shared_modules / "pacote.txt").read_text(encoding="utf-8") == "não apague"


def test_cleanup_refuses_paths_outside_workspace(harness, tmp_path):
    outside = tmp_path / "fora"
    outside.mkdir()
    with pytest.raises(ValueError, match="fora do workspace"):
        harness.cleanup(outside)
    assert outside.exists()


def test_remove_dir_link_ignores_real_directories(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (real / "a.txt").write_text("a", encoding="utf-8")
    remove_dir_link(real)  # diretório de verdade: não remove
    assert (real / "a.txt").is_file()


def test_prepare_run_dir_rejects_unsafe_ids(harness):
    for bad in ("../x", "a/b", "a b", ""):
        with pytest.raises(ValueError, match="run_id inválido"):
            harness.prepare_run_dir(bad)


def test_static_server_serves_js_as_javascript_and_is_quiet(tmp_path):
    (tmp_path / "index.html").write_text("<h1>oi</h1>", encoding="utf-8")
    (tmp_path / "main.js").write_text("export const x = 1;", encoding="utf-8")
    (tmp_path / "f.woff2").write_bytes(b"\x00")
    with StaticServer(tmp_path) as srv:
        with urllib.request.urlopen(srv.url + "main.js") as r:
            assert r.headers["Content-Type"].startswith("text/javascript")
            assert r.headers["Cache-Control"] == "no-store"
        with urllib.request.urlopen(srv.url) as r:
            assert b"<h1>oi</h1>" in r.read()
        with urllib.request.urlopen(srv.url + "f.woff2") as r:
            assert r.headers["Content-Type"] == "font/woff2"
        url = srv.url
    with pytest.raises(OSError):  # parou de verdade
        urllib.request.urlopen(url, timeout=2)


def test_static_server_rejects_missing_directory(tmp_path):
    with pytest.raises(FileNotFoundError):
        StaticServer(tmp_path / "nao_existe")


@pytest.mark.skipif(os.name != "nt", reason="junction é específico do Windows")
def test_windows_link_is_a_junction(tmp_path):
    target = tmp_path / "t"
    target.mkdir()
    link = tmp_path / "l"
    make_dir_link(link, target)
    assert os.path.isjunction(link)
    remove_dir_link(link)
    assert not link.exists() and target.exists()
