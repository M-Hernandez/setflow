"""Tests for the Spotify client wrapper."""

from unittest.mock import MagicMock, patch

import pytest
import spotipy.exceptions

from app.ingestion.spotify_client import (
    SpotifyClient,
    SpotifyRateLimitError,
    SpotifyResult,
)


@pytest.fixture
def mock_spotipy():
    """Patch spotipy.Spotify, SpotifyClientCredentials, and time.sleep."""
    with (
        patch("app.ingestion.spotify_client.SpotifyClientCredentials"),
        patch("app.ingestion.spotify_client.spotipy.Spotify") as mock_cls,
        patch("app.ingestion.spotify_client.time.sleep"),
        patch("app.ingestion.spotify_client.time.monotonic", return_value=0.0),
    ):
        mock_sp = MagicMock()
        mock_cls.return_value = mock_sp
        yield mock_sp


@pytest.fixture
def client(mock_spotipy):
    return SpotifyClient()


def _make_429(retry_after: str) -> spotipy.exceptions.SpotifyException:
    error = spotipy.exceptions.SpotifyException(429, -1, "rate limited")
    error.headers = {"Retry-After": retry_after}
    return error


def _make_search_result(uri="spotify:track:abc123", name="Track", artist="Artist"):
    return {
        "tracks": {
            "items": [
                {
                    "uri": uri,
                    "duration_ms": 300000,
                    "name": name,
                    "artists": [{"name": artist}],
                    "external_ids": {"isrc": "TEST12345678"},
                }
            ]
        }
    }


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
        mock_spotipy.search.return_value = _make_search_result()

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


class TestSoftRateLimit:
    """Retry-After ≤ 60s: sleep and resume."""

    def test_soft_limit_retries_and_succeeds(self, client, mock_spotipy):
        mock_spotipy.search.side_effect = [
            _make_429("2"),
            _make_search_result(),
        ]

        result = client.search_track("Artist", "Track")
        assert result is not None
        assert result.spotify_uri == "spotify:track:abc123"
        assert mock_spotipy.search.call_count == 2
        assert not client.is_disabled

    def test_soft_limit_multiple_retries(self, client, mock_spotipy):
        mock_spotipy.search.side_effect = [
            _make_429("1"),
            _make_429("2"),
            _make_429("3"),
            _make_search_result(),
        ]

        result = client.search_track("Artist", "Track")
        assert result is not None
        assert mock_spotipy.search.call_count == 4
        assert not client.is_disabled

    def test_retries_exhausted_client_stays_alive(self, client, mock_spotipy):
        """All retries used on soft limits — skip track but don't kill client."""
        mock_spotipy.search.side_effect = _make_429("1")

        result = client.search_track("Artist", "Track", max_retries=3)
        assert result is None
        assert not client.is_disabled  # Client stays alive!

        # Next track should still work
        mock_spotipy.search.side_effect = None
        mock_spotipy.search.return_value = _make_search_result(uri="spotify:track:next")
        result2 = client.search_track("Artist2", "Track2")
        assert result2 is not None
        assert result2.spotify_uri == "spotify:track:next"


class TestMediumRateLimit:
    """Retry-After 60-600s: sleep, slow down throttle, resume."""

    def test_medium_limit_slows_throttle(self, client, mock_spotipy):
        mock_spotipy.search.side_effect = [
            _make_429("120"),
            _make_search_result(),
        ]

        result = client.search_track("Artist", "Track")
        assert result is not None
        assert not client.is_disabled
        assert client._request_interval == 3.0  # Throttle bumped


class TestHardRateLimit:
    """Retry-After > 600s: kill client for session."""

    def test_hard_limit_kills_client(self, client, mock_spotipy):
        mock_spotipy.search.side_effect = _make_429("3600")

        with pytest.raises(SpotifyRateLimitError):
            client.search_track("Artist", "Track")

        assert client.is_disabled

    def test_disabled_client_returns_none(self, client, mock_spotipy):
        mock_spotipy.search.side_effect = _make_429("3600")

        with pytest.raises(SpotifyRateLimitError):
            client.search_track("Artist", "Track")

        # All subsequent calls return None without hitting API
        mock_spotipy.search.reset_mock()
        result = client.search_track("Other", "Song")
        assert result is None
        assert mock_spotipy.search.call_count == 0


class TestThrottle:
    def test_default_interval_is_2s(self, client):
        assert client._request_interval == 2.0
