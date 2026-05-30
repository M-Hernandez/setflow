"""Tests for /test-claude and /test-embed routes."""

from unittest.mock import AsyncMock, patch


# --- /test-claude ---


async def test_claude_returns_response(client, monkeypatch):
    monkeypatch.setattr("app.api.test_llm.settings.anthropic_api_key", "sk-fake")

    mock_message = AsyncMock()
    mock_message.model = "claude-haiku-4-5-20251001"
    mock_message.content = [AsyncMock(text="Hello! How can I help you today?")]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_message)

    with patch("app.api.test_llm.anthropic.AsyncAnthropic", return_value=mock_client):
        response = await client.get("/test-claude")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["model"] == "claude-haiku-4-5-20251001"
    assert "Hello" in data["response"]


async def test_claude_missing_key(client, monkeypatch):
    monkeypatch.setattr("app.api.test_llm.settings.anthropic_api_key", "")

    response = await client.get("/test-claude")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "error"
    assert "ANTHROPIC_API_KEY" in data["detail"]


async def test_claude_api_error(client, monkeypatch):
    monkeypatch.setattr("app.api.test_llm.settings.anthropic_api_key", "sk-bad")

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(
        side_effect=__import__("anthropic").APIConnectionError(request=None)
    )

    with patch("app.api.test_llm.anthropic.AsyncAnthropic", return_value=mock_client):
        response = await client.get("/test-claude")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "error"


# --- /test-embed ---


async def test_embed_returns_vector(client, monkeypatch):
    monkeypatch.setattr("app.api.test_llm.settings.voyage_api_key", "voy-fake")

    fake_vector = [0.1] * 1024
    mock_result = AsyncMock()
    mock_result.embeddings = [fake_vector]

    mock_client = AsyncMock()
    mock_client.embed = AsyncMock(return_value=mock_result)

    with patch("app.api.test_llm.voyageai.AsyncClient", return_value=mock_client):
        response = await client.get("/test-embed")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["dimensions"] == 1024
    assert len(data["preview"]) == 5


async def test_embed_missing_key(client, monkeypatch):
    monkeypatch.setattr("app.api.test_llm.settings.voyage_api_key", "")

    response = await client.get("/test-embed")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "error"
    assert "VOYAGE_API_KEY" in data["detail"]


async def test_embed_api_error(client, monkeypatch):
    monkeypatch.setattr("app.api.test_llm.settings.voyage_api_key", "voy-bad")

    mock_client = AsyncMock()
    mock_client.embed = AsyncMock(side_effect=Exception("connection refused"))

    with patch("app.api.test_llm.voyageai.AsyncClient", return_value=mock_client):
        response = await client.get("/test-embed")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "error"
    assert "connection refused" in data["detail"]
