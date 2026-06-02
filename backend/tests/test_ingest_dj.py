"""Tests for the DJ ingestion orchestrator."""

import pytest

from app.ingestion.ingest_dj import (
    ScrapedSet,
    _dedup_key,
    _make_slug,
    deduplicate_sets,
)
from app.ingestion.parse_tracklist import ParsedTrack


def _make_track(position=1, artist="Artist", title="Title"):
    return ParsedTrack(
        position=position, timestamp="0:00", timestamp_seconds=0.0,
        artist=artist, title=title,
    )


class TestMakeSlug:
    def test_basic(self):
        assert _make_slug("Adam Beyer") == "adam-beyer"

    def test_special_chars(self):
        assert _make_slug("ARTBAT") == "artbat"

    def test_ampersand(self):
        assert _make_slug("Above & Beyond") == "above-beyond"


class TestDeduplication:
    def test_same_date_deduplicates(self):
        """Sets from the same date should be deduplicated."""
        from datetime import date

        s1 = ScrapedSet(
            title="YT Set", source="youtube", event_date=date(2024, 6, 15),
            tracks=[_make_track(1), _make_track(2)],
        )
        s2 = ScrapedSet(
            title="MDB Set", source="mixesdb", event_date=date(2024, 6, 15),
            tracks=[_make_track(1)],
        )
        result = deduplicate_sets([s1, s2])
        assert len(result) == 1
        # s1 has more tracks
        assert result[0].source == "youtube"

    def test_different_dates_kept(self):
        from datetime import date

        s1 = ScrapedSet(
            title="Set A", source="youtube", event_date=date(2024, 6, 15),
            tracks=[_make_track(1)],
        )
        s2 = ScrapedSet(
            title="Set B", source="mixesdb", event_date=date(2024, 7, 20),
            tracks=[_make_track(1)],
        )
        result = deduplicate_sets([s1, s2])
        assert len(result) == 2

    def test_prefer_more_tracks(self):
        """When dates match, prefer the set with more tracks."""
        from datetime import date

        s1 = ScrapedSet(
            title="Few tracks", source="youtube", event_date=date(2024, 1, 1),
            tracks=[_make_track(1)],
        )
        s2 = ScrapedSet(
            title="Many tracks", source="mixesdb", event_date=date(2024, 1, 1),
            tracks=[_make_track(1), _make_track(2), _make_track(3)],
        )
        result = deduplicate_sets([s1, s2])
        assert len(result) == 1
        assert result[0].source == "mixesdb"

    def test_prefer_youtube_on_tie(self):
        """When track counts match, prefer YouTube (has timestamps)."""
        from datetime import date

        s1 = ScrapedSet(
            title="MDB", source="mixesdb", event_date=date(2024, 1, 1),
            tracks=[_make_track(1)],
        )
        s2 = ScrapedSet(
            title="YT", source="youtube", event_date=date(2024, 1, 1),
            tracks=[_make_track(1)],
        )
        result = deduplicate_sets([s1, s2])
        assert len(result) == 1
        assert result[0].source == "youtube"

    def test_no_date_falls_back_to_title(self):
        """Sets without dates should dedup by normalized title."""
        s1 = ScrapedSet(
            title="  Some Title  ", source="youtube",
            tracks=[_make_track(1)],
        )
        s2 = ScrapedSet(
            title="some title", source="mixesdb",
            tracks=[_make_track(1), _make_track(2)],
        )
        result = deduplicate_sets([s1, s2])
        assert len(result) == 1

    def test_empty_list(self):
        assert deduplicate_sets([]) == []
