"""Tests for Deezer ISRC → BPM lookup."""

import httpx
import pytest
from unittest.mock import AsyncMock, patch

from app.ingestion.deezer_lookup import DeezerMatch, lookup_by_isrc


@pytest.fixture
def mock_client():
    return AsyncMock(spec=httpx.AsyncClient)


def _make_response(json_data: dict, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        json=json_data,
        request=httpx.Request("GET", "https://api.deezer.com/test"),
    )


async def test_valid_isrc_returns_bpm(mock_client):
    mock_client.get.return_value = _make_response({
        "id": 12345,
        "bpm": 124.5,
        "title": "Test Track",
        "artist": {"name": "Test Artist"},
    })
    result = await lookup_by_isrc(mock_client, "USRC12345678")
    assert result == DeezerMatch(deezer_id=12345, bpm=124.5)
    mock_client.get.assert_called_once()


async def test_unknown_isrc_returns_none(mock_client):
    mock_client.get.return_value = _make_response({
        "error": {"type": "DataException", "message": "no data", "code": 800},
    })
    result = await lookup_by_isrc(mock_client, "XXXX00000000")
    assert result is None


async def test_zero_bpm_treated_as_none(mock_client):
    mock_client.get.return_value = _make_response({
        "id": 99999,
        "bpm": 0,
        "title": "Unknown BPM Track",
    })
    result = await lookup_by_isrc(mock_client, "USRC00000001")
    assert result is not None
    assert result.deezer_id == 99999
    assert result.bpm is None


async def test_network_error_returns_none(mock_client):
    mock_client.get.side_effect = httpx.ConnectError("connection refused")
    result = await lookup_by_isrc(mock_client, "USRC12345678")
    assert result is None


async def test_timeout_returns_none(mock_client):
    mock_client.get.side_effect = httpx.TimeoutException("timed out")
    result = await lookup_by_isrc(mock_client, "USRC12345678")
    assert result is None


async def test_missing_id_returns_none(mock_client):
    mock_client.get.return_value = _make_response({"bpm": 120})
    result = await lookup_by_isrc(mock_client, "USRC12345678")
    assert result is None
