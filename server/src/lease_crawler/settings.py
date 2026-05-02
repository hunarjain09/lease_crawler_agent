"""Application settings, loaded from env and the repo-root .env file (if present)."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# server/src/lease_crawler/settings.py -> repo root is three parents up from this file's dir.
_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Server settings.

    M0 only exposed host/port. M2 adds GMI Cloud LLM config.
    """

    SERVER_HOST: str = "127.0.0.1"
    SERVER_PORT: int = 8000

    # GMI Cloud serverless (OpenAI-compatible). API key is required at runtime
    # but defaulted here so unit tests that import settings without env loaded
    # don't blow up; the real value comes from `.env` or the process env.
    GMI_API_KEY: str = ""
    GMI_LLM_BASE_URL: str = "https://api.gmi-serving.com/v1"
    GMI_LLM_MODEL: str = "anthropic/claude-opus-4.7"

    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )


def get_settings() -> Settings:
    """Return a fresh Settings instance.

    Not cached so tests can monkeypatch env vars freely. Callers that want caching
    should wrap this themselves.
    """
    return Settings()
