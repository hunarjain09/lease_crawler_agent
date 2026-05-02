"""Integration test for the Obscura wrapper.

Skipped unless OBSCURA_BIN points at an executable. When it runs, it boots a
local HTTP server with a JS-injected token to prove Obscura actually executes
JavaScript (not just fetches bytes).
"""

from __future__ import annotations

import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from lease_crawler import crawler
from lease_crawler.settings import get_settings

pytestmark = pytest.mark.integration

_HTML = b"""<!doctype html>
<html><head><title>t</title></head>
<body>
  <div id="target">before</div>
  <script>
    document.getElementById('target').textContent = 'RENDERED-OK';
    document.body.dataset.token = 'RENDERED-OK';
  </script>
</body></html>
"""


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(_HTML)))
        self.end_headers()
        self.wfile.write(_HTML)

    def log_message(self, *_args: object) -> None:  # silence default stderr noise
        return None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def static_server() -> tuple[str, ThreadingHTTPServer]:
    port = _free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}/index.html", server
    server.shutdown()
    server.server_close()


@pytest.fixture(autouse=True)
def _skip_without_obscura() -> None:
    binary = get_settings().OBSCURA_BIN
    p = Path(binary)
    if not p.is_file() or not os.access(p, os.X_OK):
        pytest.skip(f"OBSCURA_BIN not present or not executable: {binary}")


@pytest.mark.asyncio
async def test_obscura_executes_js(static_server: tuple[str, ThreadingHTTPServer]) -> None:
    url, _ = static_server
    result = await crawler.crawl(url, timeout_s=20.0)
    assert "RENDERED-OK" in result.content, "Obscura did not execute JS — token missing from rendered HTML"
