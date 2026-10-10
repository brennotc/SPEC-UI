"""capture_initial_render: um app que não termina de carregar é falha DO APP (render_ok=False), não traceback (navegador real)."""

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from specui.harness import BrowserSession
from specui.harness import browser as browser_module

pytestmark = pytest.mark.slow


class _Hang(BaseHTTPRequestHandler):
    def do_GET(self):
        time.sleep(3)  # nunca responde dentro do prazo do goto
        try:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<app-root><p>x</p></app-root>")
        except OSError:
            pass

    def log_message(self, *args):  # silencioso
        pass


def test_load_timeout_is_render_failed_not_an_exception(tmp_path, monkeypatch):
    monkeypatch.setattr(browser_module, "GOTO_TIMEOUT_MS", 600)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Hang)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with BrowserSession() as session:
            art = session.capture_initial_render(f"http://127.0.0.1:{server.server_address[1]}/", (1440, 900), tmp_path)
    finally:
        server.shutdown()
        server.server_close()
    assert art.render_ok is False and art.screenshot_path is None
    assert any("não terminou de carregar" in e and "TimeoutError" in e for e in art.errors)
