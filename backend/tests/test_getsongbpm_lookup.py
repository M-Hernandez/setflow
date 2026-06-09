"""Tests for GetSongBPM artist+title → BPM+key lookup."""

import httpx
import pytest
from unittest.mock import AsyncMock

from app.ingestion.getsongbpm_lookup import (
    GetSongBPMMatch,
    _normalize_key,
    search,
)

API_KEY = "test-api-key"


def _req():
    return httpx.Request("GET", "https://api.getsongbpm.com/test")


@pytest.fixture
def mock_client():
    return AsyncMock(spec=httpx.AsyncClient)


# --- Key normalization tests ---


def test_normalize_short_minor():
    assert _normalize_key("Em") == "E Minor"


def test_normalize_short_major():
    assert _normalize_key("A") == "A Major"


def test_normalize_sharp_minor():
    assert _normalize_key("C#m") == "C# Minor"


def test_normalize_flat_major():
    assert _normalize_key("Bb") == "Bb Major"


def test_normalize_long_form_passthrough():
    assert _normalize_key("A minor") == "A Minor"


def test_normalize_empty_returns_none():
    assert _normalize_key("") is None


def test_normalize_none_input():
    assert _normalize_key("  ") is None


# --- Search tests ---


async def test_search_returns_bpm_and_key(mock_client):
    """Two-step lookup: search returns ID, detail returns BPM+key."""
    mock_client.get.side_effect = [
        # Step 1: search response
        httpx.Response(
            200,
            json={"search": [{"id": "abc123", "name": "Test Track"}]},
            request=_req(),
        ),
        # Step 2: detail response
        httpx.Response(
            200,
            json={"song": {"tempo": "124", "key_of": "Am"}},
            request=_req(),
        ),
    ]
    result = await search(mock_client, "Test Artist", "Test Track", API_KEY)
    assert result == GetSongBPMMatch(bpm=124.0, key="A Minor")
    assert mock_client.get.call_count == 2


async def test_search_no_results_returns_none(mock_client):
    mock_client.get.return_value = httpx.Response(
        200,
        json={"search": {"error": "No results"}},
        request=_req(),
    )
    result = await search(mock_client, "Unknown", "Track", API_KEY)
    assert result is None


async def test_search_empty_list_returns_none(mock_client):
    mock_client.get.return_value = httpx.Response(
        200, json={"search": []}, request=_req()
    )
    result = await search(mock_client, "Unknown", "Track", API_KEY)
    assert result is None


async def test_search_network_error_returns_none(mock_client):
    mock_client.get.side_effect = httpx.ConnectError("connection refused")
    result = await search(mock_client, "Artist", "Track", API_KEY)
    assert result is None


async def test_search_no_api_key_returns_none(mock_client):
    result = await search(mock_client, "Artist", "Track", "")
    assert result is None
    mock_client.get.assert_not_called()


async def test_search_detail_failure_returns_none(mock_client):
    """Search succeeds but detail call fails."""
    mock_client.get.side_effect = [
        httpx.Response(
            200,
            json={"search": [{"id": "abc123"}]},
            request=_req(),
        ),
        httpx.ConnectError("detail call failed"),
    ]
    result = await search(mock_client, "Artist", "Track", API_KEY)
    assert result is None


async def test_search_zero_bpm_treated_as_none(mock_client):
    mock_client.get.side_effect = [
        httpx.Response(
            200,
            json={"search": [{"id": "x"}]},
            request=_req(),
        ),
        httpx.Response(
            200,
            json={"song": {"tempo": "0", "key_of": "Dm"}},
            request=_req(),
        ),
    ]
    result = await search(mock_client, "Artist", "Track", API_KEY)
    assert result is not None
    assert result.bpm is None
    assert result.key == "D Minor"
