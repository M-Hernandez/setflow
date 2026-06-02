"""Tests for the Spotify client wrapper."""

from unittest.mock import MagicMock, patch

import pytest
import spotipy.exceptions

from app.ingestion.spotify_client import SpotifyClient, SpotifyResult


@pytest.fixture
def mock_spotipy():
    """Patch spotipy.Spotify and SpotifyClientCredentials."""
    with (
        patch("app.ingestion.spotify_client.SpotifyClientCredentials"),
        patch("app.ingestion.spotify_client.spotipy.Spotify") as mock_cls,
    ):
        mock_sp = MagicMock()
        mock_cls.return_value = mock_sp
        yield mock_sp


@pytest.fixture
def client(mock_spotipy):
    return SpotifyClient()


class TestSpotifySearch:
    def test_search_returns_result(self, client, mock_spotipy):
        mock_spotipy.search.return_value = {
            "tracks": {
                "items": [
                    {
                        "uri": "spotify:track:abc123",
                        "duration_ms": 420000,
                        "name": "Return To Oz",
                        "artists": [{"name": "Monolink"}],
                        "external_ids": {"isrc": "DEAB12345678"},
                    }
                ]
            }
        }

        result = client.search_track("Monolink", "Return To Oz")
        assert isinstance(result, SpotifyResult)
        assert result.spotify_uri == "spotify:track:abc123"
        assert result.isrc == "DEAB12345678"
        assert result.duration_ms == 420000

    def test_search_with_remix(self, client, mock_spotipy):
        mock_spotipy.search.return_value = {
            "tracks": {
                "items": [
                    {
                        "uri": "spotify:track:xyz789",
                        "duration_ms": 510000,
                        "name": "Return To Oz (ARTBAT Remix)",
                        "artists": [{"name": "Monolink"}],
                        "external_ids": {"isrc": "DEAB99999999"},
                    }
                ]
            }
        }

        result = client.search_track("Monolink", "Return To Oz", "ARTBAT Remix")
        assert result is not None
        assert result.isrc == "DEAB99999999"
        # Verify query included remix
        call_args = mock_spotipy.search.call_args
        assert "ARTBAT Remix" in call_args[1]["q"] or "ARTBAT Remix" in call_args[0][0]

    def test_search_no_results(self, client, mock_spotipy):
        mock_spotipy.search.return_value = {"tracks": {"items": []}}
        result = client.search_track("Unknown", "Nonexistent Track")
        assert result is None

    def test_caching(self, client, mock_spotipy):
        mock_spotipy.search.return_value = {
            "tracks": {
                "items": [
                    {
                        "uri": "spotify:track:abc",
                        "duration_ms": 300000,
                        "name": "Test",
                        "artists": [{"name": "Artist"}],
                        "external_ids": {},
                    }
                ]
            }
        }

        # First call hits API
        result1 = client.search_track("Artist", "Test")
        # Second call should use cache
        result2 = client.search_track("Artist", "Test")

        assert result1 == result2
        assert mock_spotipy.search.call_count == 1

    def test_caching_none_results(self, client, mock_spotipy):
        mock_spotipy.search.return_value = {"tracks": {"items": []}}

        client.search_track("Unknown", "Nothing")
        client.search_track("Unknown", "Nothing")

        assert mock_spotipy.search.call_count == 1

    def test_rate_limit_retry(self, client, mock_spotipy):
        error = spotipy.exceptions.SpotifyException(
            429, -1, "rate limited"
        )
        error.headers = {"Retry-After": "0"}

        mock_spotipy.search.side_effect = [
            error,
            {"tracks": {"items": [
                {
                    "uri": "spotify:track:after_retry",
                    "duration_ms": 300000,
                    "name": "Track",
                    "artists": [{"name": "Artist"}],
                    "external_ids": {},
                }
            ]}},
        ]

        result = client.search_track("Artist", "Track")
        assert result is not None
        assert result.spotify_uri == "spotify:track:after_retry"
        assert mock_spotipy.search.call_count == 2

    def test_rate_limit_exhausted(self, client, mock_spotipy):
        error = spotipy.exceptions.SpotifyException(
            429, -1, "rate limited"
        )
        error.headers = {"Retry-After": "0"}
        mock_spotipy.search.side_effect = error

        result = client.search_track("Artist", "Track", max_retries=2)
        assert result is None

    def test_non_429_error_returns_none(self, client, mock_spotipy):
        mock_spotipy.search.side_effect = spotipy.exceptions.SpotifyException(
            403, -1, "forbidden"
        )

        result = client.search_track("Artist", "Track")
        assert result is None

    def test_no_isrc_in_response(self, client, mock_spotipy):
        mock_spotipy.search.return_value = {
            "tracks": {
                "items": [
                    {
                        "uri": "spotify:track:noisrc",
                        "duration_ms": 300000,
                        "name": "Track",
                        "artists": [{"name": "Artist"}],
                        "external_ids": {},
                    }
                ]
            }
        }

        result = client.search_track("Artist", "Track")
        assert result is not None
        assert result.isrc is None
