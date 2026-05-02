"""Atomic tests for the Obscura wrapper. Subprocess is fully mocked."""

from __future__ import annotations

import asyncio

import pytest

from lease_crawler import crawler
from lease_crawler.crawler import CrawlError

pytestmark = pytest.mark.unit


class _FakeProc:
    def __init__(self, *, stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0, hang: bool = False) -> None:
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode
        self._hang = hang

    async def communicate(self) -> tuple[bytes, bytes]:
        if self._hang:
            await asyncio.sleep(60)
        return self._stdout, self._stderr

    def kill(self) -> None:  # pragma: no cover - exercised in timeout path
        return None

    async def wait(self) -> int:  # pragma: no cover - exercised in timeout path
        return self.returncode


def _patch_exec(monkeypatch: pytest.MonkeyPatch, proc: _FakeProc) -> None:
    async def fake_exec(*_args: object, **_kwargs: object) -> _FakeProc:
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)


@pytest.mark.asyncio
async def test_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_exec(monkeypatch, _FakeProc(stdout=b"<html>$3,415</html>", returncode=0))
    result = await crawler.crawl("https://example.com")
    assert "$3,415" in result.content
    assert result.status == 200
    assert result.url == "https://example.com"


@pytest.mark.asyncio
async def test_nonzero_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_exec(monkeypatch, _FakeProc(stderr=b"boom", returncode=1))
    with pytest.raises(CrawlError) as ei:
        await crawler.crawl("https://example.com")
    assert ei.value.reason == "nonzero_exit"
    assert "boom" in ei.value.detail


@pytest.mark.asyncio
async def test_empty_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_exec(monkeypatch, _FakeProc(stdout=b"   \n", returncode=0))
    with pytest.raises(CrawlError) as ei:
        await crawler.crawl("https://example.com")
    assert ei.value.reason == "empty"


@pytest.mark.asyncio
async def test_binary_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(*_args: object, **_kwargs: object) -> _FakeProc:
        raise FileNotFoundError(2, "no such file", "/nope/obscura")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", boom)
    with pytest.raises(CrawlError) as ei:
        await crawler.crawl("https://example.com")
    assert ei.value.reason == "binary_missing"


@pytest.mark.asyncio
async def test_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_exec(monkeypatch, _FakeProc(hang=True))
    with pytest.raises(CrawlError) as ei:
        await crawler.crawl("https://example.com", timeout_s=0.05)
    assert ei.value.reason == "timeout"
