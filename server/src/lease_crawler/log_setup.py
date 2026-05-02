"""Centralized stdlib logging setup with a request_id contextvar.

Format: `LEVEL [req_id] event key=value key=value`. Human-readable, easy to
grep, no new deps. Use `log_event(logger, "stage.event", **kwargs)` from
anywhere in the request path; the request_id is bound by the middleware in
`main.py`.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any

_request_id: ContextVar[str] = ContextVar("request_id", default="-")


def set_request_id(value: str) -> None:
    _request_id.set(value)


def get_request_id() -> str:
    return _request_id.get()


class RequestIdFilter(logging.Filter):
    """Inject the current request_id into every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        return True


_FORMAT = "%(asctime)s %(levelname)-5s [%(request_id)s] %(name)s: %(message)s"


def configure_logging(level: int = logging.INFO) -> None:
    """Configure root + uvicorn loggers once. Idempotent."""
    root = logging.getLogger()
    root.handlers.clear()  # avoid duplicate handlers under uvicorn reload
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt="%H:%M:%S"))
    handler.addFilter(RequestIdFilter())
    root.addHandler(handler)
    root.setLevel(level)

    # Quiet down noisy libs while keeping our app + uvicorn access logs.
    for noisy in ("httpx", "httpcore", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    """Emit `event key=value ...` so logs are grep-friendly without JSON deps."""
    if not fields:
        logger.info(event)
        return
    parts = [f"{k}={_stringify(v)}" for k, v in fields.items()]
    logger.info("%s %s", event, " ".join(parts))


def _stringify(v: Any) -> str:
    s = str(v)
    # Quote values that contain spaces so key=value parsing stays sane.
    if " " in s or "\t" in s:
        s = s.replace('"', '\\"')
        return f'"{s}"'
    return s
