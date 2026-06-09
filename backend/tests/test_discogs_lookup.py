"""Tests for the Discogs API lookup client."""

import httpx
import pytest
from unittest.mock import AsyncMock

from app.ingestion.discogs_lookup import (
    DiscogsMatch,
    FUZZY_THRESHOLD,
    _score_result,
    search_label_styles,
    search_track,
)


@pytest.fixture
def mock_client():
    return AsyncMock(spec=httpx.AsyncClient)


def _make_response(json_data: dict, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        json=json_data,
        request=httpx.Request("GET", "https://api.discogs.com/test"),
    )


def _make_discogs_result(
    title="TestArtist - Test Track",
    style=None,
    label=None,
    year=2023,
    id=12345,
):
    return {
        "id": id,
        "title": title,
        "style": style or ["Tech House"],
        "label": label or ["TestLabel"],
        "year": year,
    }


class TestScoreResult:
    def test_exact_match(self):
        result = _make_discogs_result(title="Solomun - After Rain")
        score = _score_result(result, "solomun", "after rain")
        assert score >= 90

    def test_partial_artist_match(self):
        result = _make_discogs_result(title="Solomun feat. Someone - After Rain")
        score = _score_result(result, "solomun", "after rain")
        assert score >= 60

    def test_no_match(self):
        result = _make_discogs_result(title="Completely Different - Other Song")
        score = _score_result(result, "solomun", "after rain")
        assert score < FUZZY_THRESHOLD

    def test_no_separator_in_title(self):
        """Discogs title without ' - ' separator."""
        result = _make_discogs_result(title="Some Album Title")
        score = _score_result(result, "solomun", "after rain")
        assert isinstance(score, float)


class TestSearchTrack:
    async def test_returns_match_above_threshold(self, mock_client):
        mock_client.get.return_value = _make_response({
            "results": [
                _make_discogs_result(
                    title="TestArtist - Test Track",
                    style=["Deep House", "Tech House"],
                    label=["Innervisions"],
                    year=2022,
                    id=99001,
                ),
            ]
        })

        result = await search_track(mock_client, "testartist", "test track")

        assert result is not None
        assert result.discogs_id == 99001
        assert result.styles == ["Deep House", "Tech House"]
        assert result.label == "Innervisions"
        assert result.year == 2022
        assert result.match_method == "track"

    async def test_returns_none_below_threshold(self, mock_client):
        mock_client.get.return_value = _make_response({
            "results": [
                _make_discogs_result(
                    title="Completely Unrelated - Different Song",
                ),
            ]
        })

        result = await search_track(mock_client, "testartist", "test track")
        assert result is None

    async def test_returns_none_on_empty_results(self, mock_client):
        mock_client.get.return_value = _make_response({"results": []})

        result = await search_track(mock_client, "testartist", "test track")
        assert result is None

    async def test_returns_none_on_network_error(self, mock_client):
        mock_client.get.side_effect = httpx.ConnectError("connection failed")

        result = await search_track(mock_client, "testartist", "test track")
        assert result is None

    async def test_returns_none_on_timeout(self, mock_client):
        mock_client.get.side_effect = httpx.TimeoutException("timeout")

        result = await search_track(mock_client, "testartist", "test track")
        assert result is None

    async def test_passes_auth_token(self, mock_client):
        mock_client.get.return_value = _make_response({"results": []})

        await search_track(mock_client, "artist", "title", token="mytoken123")

        call_kwargs = mock_client.get.call_args
        headers = call_kwargs.kwargs.get("headers", {})
        assert headers.get("Authorization") == "Discogs token=mytoken123"

    async def test_no_auth_header_without_token(self, mock_client):
        mock_client.get.return_value = _make_response({"results": []})

        await search_track(mock_client, "artist", "title", token=None)

        call_kwargs = mock_client.get.call_args
        headers = call_kwargs.kwargs.get("headers", {})
        assert "Authorization" not in headers

    async def test_label_from_list(self, mock_client):
        """Label field is a list in Discogs API — extract first element."""
        mock_client.get.return_value = _make_response({
            "results": [
                _make_discogs_result(
                    title="TestArtist - Test Track",
                    label=["Label One", "Label Two"],
                ),
            ]
        })

        result = await search_track(mock_client, "testartist", "test track")
        assert result is not None
        assert result.label == "Label One"

    async def test_no_label_field(self, mock_client):
        """Handle missing label gracefully."""
        mock_client.get.return_value = _make_response({
            "results": [
                {
                    "id": 555,
                    "title": "TestArtist - Test Track",
                    "style": ["House"],
                    "year": 2023,
                },
            ]
        })

        result = await search_track(mock_client, "testartist", "test track")
        assert result is not None
        assert result.label is None


class TestSearchLabelStyles:
    async def test_aggregates_styles_by_frequency(self, mock_client):
        mock_client.get.return_value = _make_response({
            "results": [
                {"id": 1, "style": ["Tech House", "Deep House"], "label": ["Innervisions"]},
                {"id": 2, "style": ["Tech House", "Minimal"], "label": ["Diynamic"]},
                {"id": 3, "style": ["Tech House"], "label": ["Afterlife"]},
            ]
        })

        result = await search_label_styles(mock_client, "solomun")

        assert result is not None
        assert result.match_method == "label_fallback"
        # Tech House appears 3x, should be first
        assert result.styles[0] == "Tech House"
        assert "Deep House" in result.styles
        assert "Minimal" in result.styles
        assert result.label == "Innervisions"

    async def test_returns_none_on_empty_results(self, mock_client):
        mock_client.get.return_value = _make_response({"results": []})

        result = await search_label_styles(mock_client, "unknown_artist")
        assert result is None

    async def test_returns_none_on_no_styles(self, mock_client):
        mock_client.get.return_value = _make_response({
            "results": [
                {"id": 1, "label": ["SomeLabel"]},
                {"id": 2, "label": ["OtherLabel"]},
            ]
        })

        result = await search_label_styles(mock_client, "artist")
        assert result is None

    async def test_returns_none_on_network_error(self, mock_client):
        mock_client.get.side_effect = httpx.ConnectError("connection failed")

        result = await search_label_styles(mock_client, "artist")
        assert result is None
