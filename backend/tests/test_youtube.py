"""Tests for YouTube yt-dlp wrapper with mocked yt-dlp calls."""

import json
from unittest.mock import MagicMock, patch

from app.ingestion import youtube


@patch("app.ingestion.youtube.yt_dlp.YoutubeDL")
def test_search_filters_short_videos(mock_ydl_class):
    mock_ydl = MagicMock()
    mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl)
    mock_ydl_class.return_value.__exit__ = MagicMock(return_value=False)
    mock_ydl.extract_info.return_value = {
        "entries": [
            {"id": "short1", "title": "Short clip", "duration": 300, "url": ""},
            {"id": "long1", "title": "DJ Set 1h", "duration": 3600, "url": ""},
            {"id": "short2", "title": "Interview", "duration": 600, "url": ""},
            {"id": "long2", "title": "DJ Set 2h", "duration": 7200, "url": ""},
        ]
    }

    results = youtube.search_dj_sets("Test DJ", limit=10, delay=0)

    assert len(results) == 2
    assert results[0]["video_id"] == "long1"
    assert results[1]["video_id"] == "long2"


@patch("app.ingestion.youtube.yt_dlp.YoutubeDL")
def test_search_respects_limit(mock_ydl_class):
    mock_ydl = MagicMock()
    mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl)
    mock_ydl_class.return_value.__exit__ = MagicMock(return_value=False)
    mock_ydl.extract_info.return_value = {
        "entries": [
            {"id": f"v{i}", "title": f"Set {i}", "duration": 3600, "url": ""}
            for i in range(20)
        ]
    }

    results = youtube.search_dj_sets("Test DJ", limit=3, delay=0)

    assert len(results) == 3


def test_cache_hit_skips_ytdlp(tmp_path, monkeypatch):
    monkeypatch.setattr(youtube, "CACHE_DIR", tmp_path)

    cached_data = {
        "video_id": "abc123",
        "title": "Cached Set",
        "description": "00:00 Artist - Track",
        "duration": 3600,
        "uploader": "Test Channel",
        "fetched_at": "2026-06-01T00:00:00+00:00",
    }
    (tmp_path / "abc123.json").write_text(json.dumps(cached_data))

    with patch("app.ingestion.youtube.yt_dlp.YoutubeDL") as mock_ydl_class:
        result = youtube.get_video_metadata("abc123", delay=0)
        mock_ydl_class.assert_not_called()

    assert result["title"] == "Cached Set"
    assert result["description"] == "00:00 Artist - Track"


@patch("app.ingestion.youtube.yt_dlp.YoutubeDL")
def test_cache_miss_fetches_and_caches(mock_ydl_class, tmp_path, monkeypatch):
    monkeypatch.setattr(youtube, "CACHE_DIR", tmp_path)

    mock_ydl = MagicMock()
    mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl)
    mock_ydl_class.return_value.__exit__ = MagicMock(return_value=False)
    mock_ydl.extract_info.return_value = {
        "title": "Live Set",
        "uploader": "DJ Channel",
        "duration": 3600,
        "description": "Tracklist here",
    }

    result = youtube.get_video_metadata("xyz789", delay=0)

    assert result["title"] == "Live Set"
    assert result["description"] == "Tracklist here"

    # Verify cache file was written
    cache_file = tmp_path / "xyz789.json"
    assert cache_file.exists()
    cached = json.loads(cache_file.read_text())
    assert cached["video_id"] == "xyz789"


@patch("app.ingestion.youtube.yt_dlp.YoutubeDL")
def test_metadata_contains_description(mock_ydl_class, tmp_path, monkeypatch):
    monkeypatch.setattr(youtube, "CACHE_DIR", tmp_path)

    mock_ydl = MagicMock()
    mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl)
    mock_ydl_class.return_value.__exit__ = MagicMock(return_value=False)
    mock_ydl.extract_info.return_value = {
        "title": "Set",
        "uploader": "DJ",
        "duration": 7200,
        "description": "00:00 Artist A - Track 1\n05:00 Artist B - Track 2",
    }

    result = youtube.get_video_metadata("desc_test", delay=0)

    assert "description" in result
    assert "Artist A" in result["description"]
