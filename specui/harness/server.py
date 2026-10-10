"""Servidor estático local para o `dist` do Angular.

Necessário porque os módulos ES do Angular não carregam via file://. Em Windows o registro do
sistema às vezes mapeia .js para text/plain (o navegador então recusa o módulo), por isso os
tipos MIME relevantes são fixados aqui.
"""

import functools
import socketserver
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import TracebackType
from typing import ClassVar, Self

_MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".map": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ico": "image/x-icon",
}


class _Handler(SimpleHTTPRequestHandler):
    extensions_map: ClassVar[dict[str, str]] = {**SimpleHTTPRequestHandler.extensions_map, **_MIME}

    def log_message(self, format: str, *args: object) -> None:
        return  # silencioso

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


class _Server(ThreadingHTTPServer):
    """ThreadingHTTPServer sem o `socket.getfqdn()` do bind padrão (lento no Windows)."""

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = str(self.server_address[0]), self.server_address[1]


class StaticServer:
    """`with StaticServer(dist_dir) as srv:` -> `srv.url` (porta livre, thread daemon)."""

    def __init__(self, directory: str | Path, host: str = "127.0.0.1", port: int = 0) -> None:
        directory = Path(directory)
        if not directory.is_dir():
            raise FileNotFoundError(f"diretório inexistente: {directory}")
        handler = functools.partial(_Handler, directory=str(directory))
        self._httpd = _Server((host, port), handler)
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        )
        self.host = host

    @property
    def port(self) -> int:
        return int(self._httpd.server_address[1])

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    def start(self) -> Self:
        self._thread.start()
        return self

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)

    def __enter__(self) -> Self:
        return self.start()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()
