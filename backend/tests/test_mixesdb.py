"""Tests for MixesDB API client with mocked HTTP calls."""

import json
from unittest.mock import MagicMock, patch

from app.ingestion import mixesdb


@patch("app.ingestion.mixesdb._api_request")
def test_search_returns_mapped_results(mock_api):
    mock_api.return_value = {
        "query": {
            "search": [
                {
                    "ns": 0,
                    "title": "2024-09-28 - ARTBAT @ Cercle",
                    "pageid": 12345,
                    "snippet": "tracklist <span>ARTBAT</span>",
                },
                {
                    "ns": 0,
                    "title": "2023-07-01 - ARTBAT @ Tomorrowland",
                    "pageid": 67890,
                    "snippet": "another set",
                },
            ]
        }
    }

    results = mixesdb.search_mixes("ARTBAT", limit=5, delay=0)

    assert len(results) == 2
    assert results[0]["title"] == "2024-09-28 - ARTBAT @ Cercle"
    assert results[0]["pageid"] == 12345
    assert results[1]["title"] == "2023-07-01 - ARTBAT @ Tomorrowland"


@patch("app.ingestion.mixesdb._api_request")
def test_search_empty_results(mock_api):
    mock_api.return_value = {"query": {"search": []}}
    results = mixesdb.search_mixes("NonexistentDJ", limit=5, delay=0)
    assert results == []


def test_cache_hit_skips_api(tmp_path, monkeypatch):
    monkeypatch.setattr(mixesdb, "CACHE_DIR", tmp_path)

    cached_data = {
        "page_title": "2024-09-28 - ARTBAT @ Cercle",
        "wikitext": "# [00] ARTBAT - Track [Label]",
        "categories": ["2024", "ARTBAT"],
        "fetched_at": "2026-06-01T00:00:00+00:00",
    }
    filename = mixesdb._sanitize_filename("2024-09-28 - ARTBAT @ Cercle")
    (tmp_path / f"{filename}.json").write_text(json.dumps(cached_data))

    with patch("app.ingestion.mixesdb._api_request") as mock_api:
        result = mixesdb.get_page_data("2024-09-28 - ARTBAT @ Cercle", delay=0)
        mock_api.assert_not_called()

    assert result["wikitext"] == "# [00] ARTBAT - Track [Label]"


@patch("app.ingestion.mixesdb._api_request")
def test_cache_miss_fetches_and_caches(mock_api, tmp_path, monkeypatch):
    monkeypatch.setattr(mixesdb, "CACHE_DIR", tmp_path)

    mock_api.return_value = {
        "parse": {
            "wikitext": {"*": "# [00] Artist - Track"},
            "categories": [{"*": "2024"}, {"*": "ARTBAT"}],
        }
    }

    result = mixesdb.get_page_data("2024-09-28 - ARTBAT @ Cercle", delay=0)

    assert result["wikitext"] == "# [00] Artist - Track"
    assert result["categories"] == ["2024", "ARTBAT"]

    # Verify cache file was written
    filename = mixesdb._sanitize_filename("2024-09-28 - ARTBAT @ Cercle")
    cache_file = tmp_path / f"{filename}.json"
    assert cache_file.exists()
    cached = json.loads(cache_file.read_text())
    assert cached["page_title"] == "2024-09-28 - ARTBAT @ Cercle"


class TestSanitizeFilename:
    def test_basic(self):
        result = mixesdb._sanitize_filename("2024-09-28 - ARTBAT @ Cercle")
        assert "/" not in result
        assert "\\" not in result

    def test_special_chars_replaced(self):
        result = mixesdb._sanitize_filename("DJ/Set: Live @ Venue (2024)")
        assert "/" not in result
        assert ":" not in result

    def test_truncation(self):
        long_title = "A" * 300
        result = mixesdb._sanitize_filename(long_title)
        assert len(result) <= 200
