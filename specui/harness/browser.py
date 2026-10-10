"""Sessão de navegador (Playwright): captura o RENDER INICIAL, sem nenhuma interação.

Regras do experimento:
- viewport = tamanho do frame do Figma, escala 1x (o screenshot é comparável pixel a pixel);
- relógio falso instalado ANTES do `goto` (datas estáveis; nada anda sozinho além do tempo real);
- rede bloqueada fora da origem local, e as URLs bloqueadas são registradas (o envelope avisa que
  não há rede: quem importa fonte/CDN externos falha por isso);
- nada de preencher campos nem clicar antes do screenshot (o código antigo fazia isso).
"""

import json
import logging
from pathlib import Path
from types import TracebackType
from typing import Any, Self
from urllib.parse import urlparse

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from pydantic import BaseModel, Field

from specui.clock import FIXED_NOW

logger = logging.getLogger(__name__)

_JS_DIR = Path(__file__).parent / "js"
ROOT_READY = "() => { const r = document.querySelector('app-root'); return !!r && r.childElementCount > 0; }"
GOTO_TIMEOUT_MS = 30_000
ROOT_TIMEOUT_MS = 15_000
_AXE_IMPACTS = ("critical", "serious", "moderate", "minor")


def load_app(
    page: Page, url: str, settle_ms: int, root_timeout_ms: int = ROOT_TIMEOUT_MS, settle_if_failed: bool = True
) -> str | None:
    """A sequência ÚNICA que leva uma página ao "app pronto": o render inicial e cada caso do oráculo usam esta função.

    goto(load) -> `app-root` com ao menos 1 filho -> `document.fonts.ready` -> espera de `settle_ms` (render_settle_ms).
    O `app-root` com um filho é só "o Angular montou algo": o conteúdo real pode vir depois (um `@if` que espera o estado
    inicial, um setTimeout, a fonte), e o primeiro caso de um Chromium recém-aberto é o que mais sofre com isso.
    Devolve None se o app-root renderizou, ou o nome da exceção (ex.: TimeoutError) se não; com `settle_if_failed=False` não
    espera os 800 ms numa página que nunca montou (o oráculo só vai bloquear o caso)."""
    page.goto(url, wait_until="load", timeout=GOTO_TIMEOUT_MS)
    error: str | None = None
    try:
        page.wait_for_function(ROOT_READY, timeout=root_timeout_ms)
    except Exception as exc:  # noqa: BLE001 - timeout = app-root nunca renderizou
        error = type(exc).__name__
    if error is None or settle_if_failed:
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(settle_ms)
    return error


def _js(name: str) -> str:
    return (_JS_DIR / name).read_text(encoding="utf-8")


class RenderArtifacts(BaseModel):
    render_ok: bool
    viewport: tuple[int, int]
    screenshot_path: str | None = None
    blocks_path: str | None = None
    css_snapshot_path: str | None = None
    axe_path: str | None = None
    console_errors: list[str] = Field(default_factory=list)
    page_errors: list[str] = Field(default_factory=list)
    blocked_requests: list[str] = Field(default_factory=list)
    axe_violations: dict[str, int] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)  # falhas das extrações (não derrubam o render)
    # Em memória, para as métricas; não vão para o record.json (estão em arquivos).
    dom_blocks: list[dict[str, Any]] = Field(default_factory=list, exclude=True)
    css_snapshot: dict[str, Any] = Field(default_factory=dict, exclude=True)


class BrowserSession:
    """Um Chromium para o pipeline inteiro; cada captura usa um contexto novo e isolado."""

    def __init__(
        self,
        clock_epoch_iso: str = FIXED_NOW,
        render_settle_ms: int = 800,
        block_network: bool = True,
        headless: bool = True,
    ) -> None:
        self.clock_epoch_iso = clock_epoch_iso
        self.render_settle_ms = render_settle_ms
        self.block_network = block_network
        self._headless = headless
        self._pw: Playwright | None = None
        self._browser: Browser | None = None

    # ------------------------------------------------------------------ ciclo de vida

    def start(self) -> Self:
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self._headless)
        return self

    def close(self) -> None:
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()
        self._browser = self._pw = None

    def __enter__(self) -> Self:
        return self.start()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def versions(self) -> tuple[str | None, str | None]:
        """(versão do Playwright, versão do Chromium): gravadas em cada run (o instrumento inclui o navegador)."""
        from importlib.metadata import PackageNotFoundError, version

        try:
            playwright_version = version("playwright")
        except PackageNotFoundError:
            playwright_version = None
        return playwright_version, (self._browser.version if self._browser else None)

    # ------------------------------------------------------------------ contexto

    def new_context(self, viewport: tuple[int, int]) -> BrowserContext:
        """Contexto padronizado (também usado pelo runner dos oráculos)."""
        if self._browser is None:
            raise RuntimeError("BrowserSession não iniciada (use `with BrowserSession(...)`)")
        return self._browser.new_context(
            viewport={"width": viewport[0], "height": viewport[1]},
            device_scale_factor=1,
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            reduced_motion="reduce",
        )

    def install_network_policy(self, context: BrowserContext, origin: str, blocked: list[str]) -> None:
        def handler(route: Any) -> None:
            url = route.request.url
            parsed = urlparse(url)
            if f"{parsed.scheme}://{parsed.netloc}" == origin or parsed.scheme in ("data", "blob", "about"):
                route.continue_()
            else:
                blocked.append(url)
                route.abort()

        context.route("**/*", handler)

    # ------------------------------------------------------------------ captura

    def capture_initial_render(
        self, url: str, viewport: tuple[int, int], out_dir: str | Path
    ) -> RenderArtifacts:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        art = RenderArtifacts(render_ok=False, viewport=viewport)
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"

        context = self.new_context(viewport)
        try:
            page = context.new_page()
            page.clock.install(time=self.clock_epoch_iso)  # antes do goto
            if self.block_network:
                self.install_network_policy(context, origin, art.blocked_requests)
            page.on("pageerror", lambda err: art.page_errors.append(str(err)))
            page.on("console", lambda msg: art.console_errors.append(msg.text) if msg.type == "error" else None)

            try:
                error = load_app(page, url, self.render_settle_ms)
            except PlaywrightTimeout:
                # o `load` não veio em GOTO_TIMEOUT_MS (ex.: laço infinito no construtor): falha do APP, não da infraestrutura.
                # Sem render não há screenshot nem extração; o pipeline grava `nonexecutable`.
                art.errors.append(f"o app não terminou de carregar em {GOTO_TIMEOUT_MS // 1000} s (TimeoutError)")
                return art
            if error is None:
                art.render_ok = True
            else:
                art.errors.append(f"app-root não renderizou: {error}")

            shot = out_dir / "screenshot.png"
            page.screenshot(path=str(shot), full_page=False)
            art.screenshot_path = str(shot)
            self._extract(page, art, out_dir)
        finally:
            context.close()
        return art

    def _extract(self, page: Page, art: RenderArtifacts, out_dir: Path) -> None:
        try:
            art.dom_blocks = page.evaluate(_js("dom_blocks.js"))
            art.blocks_path = self._dump(out_dir / "dom_blocks.json", art.dom_blocks)
        except Exception as exc:  # noqa: BLE001
            art.errors.append(f"dom_blocks falhou: {exc}")
        try:
            art.css_snapshot = page.evaluate(_js("css_snapshot.js"))
            art.css_snapshot_path = self._dump(out_dir / "css_snapshot.json", art.css_snapshot)
        except Exception as exc:  # noqa: BLE001
            art.errors.append(f"css_snapshot falhou: {exc}")
        try:
            art.axe_violations, art.axe_path = self._run_axe(page, out_dir)
        except Exception as exc:  # noqa: BLE001
            art.errors.append(f"axe falhou: {exc}")

    @staticmethod
    def _run_axe(page: Page, out_dir: Path) -> tuple[dict[str, int], str]:
        from axe_playwright_python.sync_playwright import Axe

        response = Axe().run(page).response
        counts = dict.fromkeys(_AXE_IMPACTS, 0)
        for violation in response.get("violations", []):
            impact = violation.get("impact") or "minor"
            counts[impact] = counts.get(impact, 0) + 1
        path = out_dir / "axe.json"
        path.write_text(json.dumps(response, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
        return counts, str(path)

    @staticmethod
    def _dump(path: Path, data: Any) -> str:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
        return str(path)
