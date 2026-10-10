import pytest

from specui.codegen import PathRejected, parse_bundle, validate_path
from specui.codegen.parser import MAX_FILES

APP_TS = "import { Component } from '@angular/core';\n@Component({selector: 'app-root', template: ''})\nexport class App {}\n"


def block(path: str, content: str, lang: str = "ts", fence: str = "```") -> str:
    return f"{fence}{lang} file={path}\n{content.rstrip()}\n{fence}\n"


def test_primary_format_multiple_files():
    text = (
        "Segue a implementação:\n\n"
        + block("src/app/app.ts", APP_TS)
        + block("src/app/app.html", "<h1>Oi</h1>", "html")
        + block("src/styles.css", "h1 { color: red; }", "css")
    )
    b = parse_bundle(text)
    assert b.format_ok and b.contract_ok
    assert b.parser_used == "fence_attr"
    assert [f.path for f in b.files] == ["src/app/app.ts", "src/app/app.html", "src/styles.css"]
    assert b.files[1].content == "<h1>Oi</h1>\n"
    assert len(b.files[0].sha256) == 64
    assert b.rejected == [] and b.duplicates == []


def test_crlf_is_normalized():
    text = block("src/app/app.ts", APP_TS).replace("\n", "\r\n")
    b = parse_bundle(text)
    assert b.format_ok and b.contract_ok
    assert "\r" not in b.files[0].content


@pytest.mark.parametrize("outer", ["```", "````"])
def test_outer_fence_wrapping_everything(outer):
    inner = block("src/app/app.ts", APP_TS) + block("src/app/app.html", "<p>x</p>", "html")
    b = parse_bundle(f"{outer}markdown\n{inner}{outer}\n")
    assert [f.path for f in b.files] == ["src/app/app.ts", "src/app/app.html"]
    assert b.contract_ok


@pytest.mark.parametrize(
    "first_line",
    ["// FILE: src/app/app.ts", "/* FILE: src/app/app.ts */", "<!-- FILE: src/app/app.ts -->"],
)
def test_header_comment_fallback(first_line):
    text = f"```ts\n{first_line}\n{APP_TS}```\n"
    b = parse_bundle(text)
    assert b.format_ok and b.contract_ok
    assert b.parser_used == "fence_comment"
    assert "FILE:" not in b.files[0].content


def test_alternate_attribute_names():
    for attr in ('title="src/app/app.ts"', "path=src/app/app.ts", "filename='src/app/app.ts'"):
        b = parse_bundle(f"```ts {attr}\n{APP_TS}```\n")
        assert b.format_ok, attr


@pytest.mark.parametrize(
    "path, reason",
    [
        ("../etc/passwd", "'..'"),
        ("src/app/../../x.ts", "'..'"),
        ("/abs/app.ts", "absoluto"),
        ("C:/x/app.ts", "absoluto"),
        ("cypress/e2e/pomodoro.cy.ts", "fora das áreas"),
        ("src/app/app.spec.ts", "teste"),
        ("package.json", "fora das áreas"),
        ("angular.json", "fora das áreas"),
        ("src/index.html", "fora das áreas"),
        ("src/main.ts", "fora das áreas"),
        ("src/app/img.png", "fora das áreas"),
        ("src/app//x.ts", "vazio"),
    ],
)
def test_rejected_paths_are_recorded_not_fatal(path, reason):
    b = parse_bundle(block(path, "x") + block("src/app/app.ts", APP_TS))
    assert b.format_ok and b.contract_ok  # o resto continua valendo
    assert len(b.rejected) == 1
    assert b.rejected[0][0] == path and reason in b.rejected[0][1]


def test_validate_path_normalizes():
    assert validate_path("./src\\app\\app.ts") == "src/app/app.ts"
    assert validate_path("src/styles.css") == "src/styles.css"
    with pytest.raises(PathRejected):
        validate_path("src/styles.scss")


def test_no_blocks_is_format_failure():
    b = parse_bundle("Claro! Aqui vai o código, mas não vou usar blocos.")
    assert not b.format_ok and not b.contract_ok
    assert b.parser_used == "none" and b.files == []


def test_block_without_path_is_ignored():
    b = parse_bundle("```ts\nconsole.log(1)\n```\n" + block("src/app/app.ts", APP_TS))
    assert [f.path for f in b.files] == ["src/app/app.ts"]


def test_only_rejected_paths_is_format_failure():
    b = parse_bundle(block("package.json", "{}", "json"))
    assert not b.format_ok
    assert b.rejected and b.files == []


def test_duplicate_path_last_wins():
    text = block("src/app/app.ts", "// velho\nexport class Main {}") + block("src/app/app.ts", APP_TS)
    b = parse_bundle(text)
    assert b.duplicates == ["src/app/app.ts"]
    assert b.contract_ok and len(b.files) == 1


def test_contract_requires_exported_class_App():
    for body in ("export class Main {}", "class App {}", "export class AppComponent {}"):
        assert not parse_bundle(block("src/app/app.ts", body)).contract_ok, body
    assert not parse_bundle(block("src/app/outro.ts", APP_TS)).contract_ok
    assert parse_bundle(block("src/app/app.ts", "export class App {}")).contract_ok


def test_unclosed_block_warns():
    b = parse_bundle("```ts file=src/app/app.ts\n" + APP_TS.rstrip())
    assert b.format_ok and b.contract_ok
    assert any("não foi fechado" in w for w in b.warnings)


def test_file_count_limit():
    text = "".join(block(f"src/app/c{i}.ts", "export const x = 1;") for i in range(MAX_FILES + 5))
    b = parse_bundle(text)
    assert len(b.files) == MAX_FILES
    assert len(b.rejected) == 5 and "arquivos" in b.rejected[0][1]
