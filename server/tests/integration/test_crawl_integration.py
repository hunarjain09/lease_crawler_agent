"""Integration test: crawler against a real local HTTP server (no internet)."""

from __future__ import annotations

import socket
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from lease_crawler import crawler

pytestmark = pytest.mark.integration

_HTML = b"<!doctype html><html><body><div>token=RENDERED-OK</div></body></html>"


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(_HTML)))
        self.end_headers()
        self.wfile.write(_HTML)

    def log_message(self, *_args: object) -> None:
        return None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def static_server() -> Iterator[str]:
    port = _free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{port}/"
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.asyncio
async def test_crawl_local_server(static_server: str) -> None:
    result = await crawler.crawl(static_server, timeout_s=10.0)
    assert "RENDERED-OK" in result.content
    assert result.status == 200
