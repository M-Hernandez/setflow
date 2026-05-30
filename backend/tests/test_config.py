"""Tests for configuration loading."""

from app.config import Settings


def test_settings_from_env(monkeypatch):
    """Settings should read from environment variables."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://custom:custom@db:5432/custom")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")

    s = Settings()
    assert s.database_url == "postgresql+asyncpg://custom:custom@db:5432/custom"
    assert s.anthropic_api_key == "sk-test-key"
