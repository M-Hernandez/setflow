"""Tests for Beatport reference table lookup."""

import pytest
from sqlalchemy import select

from app.ingestion.beatport_lookup import (
    FUZZY_THRESHOLD,
    BeatportMatch,
    fuzzy_match,
    lookup_by_isrc,
)
from app.models import BeatportTrack


@pytest.fixture
async def beatport_tracks(db_session):
    """Insert sample Beatport tracks for testing.

    Uses unique fake artist/track names to avoid collisions with real
    Beatport data that may be loaded in the test database.
    """
    tracks = [
        BeatportTrack(
            id=1001,
            name="Zephyr Dreams",
            mix_name="Original Mix",
            artist="TestArtistAlpha",
            label="TestLabel",
            isrc="TSAB12345678",
            bpm=122,
            key="Am",
            genre="TestGenreA",
            subgenre="TestSubgenre",
        ),
        BeatportTrack(
            id=1002,
            name="Zephyr Dreams",
            mix_name="TestArtistBeta Remix",
            artist="TestArtistAlpha",
            label="TestLabel",
            isrc="TSAB99999999",
            bpm=126,
            key="Cm",
            genre="TestGenreA",
            subgenre="TestSubgenre",
        ),
        BeatportTrack(
            id=1003,
            name="Pulse Signal",
            mix_name="Original Mix",
            artist="TestArtistGamma",
            label="TestLabelTwo",
            isrc="TSGA12345678",
            bpm=132,
            key="Bm",
            genre="TestGenreB",
            subgenre="TestSubgenreB",
        ),
        BeatportTrack(
            id=1004,
            name="Void Echo",
            mix_name=None,
            artist="TestArtistBeta",
            label="TestLabelThree",
            isrc=None,
            bpm=124,
            key="Dm",
            genre="TestGenreA",
            subgenre=None,
        ),
    ]
    db_session.add_all(tracks)
    await db_session.flush()
    return tracks


class TestLookupByISRC:
    async def test_exact_match(self, db_session, beatport_tracks):
        result = await lookup_by_isrc(db_session, "TSAB12345678")
        assert result is not None
        assert result.beatport_id == 1001
        assert result.bpm == 122
        assert result.key == "Am"
        assert result.genre == "TestGenreA"
        assert result.match_method == "isrc"

    async def test_no_match(self, db_session, beatport_tracks):
        result = await lookup_by_isrc(db_session, "XXXXXXXXXXXX")
        assert result is None

    async def test_correct_remix_via_isrc(self, db_session, beatport_tracks):
        """ISRC should return the remix, not the Original."""
        result = await lookup_by_isrc(db_session, "TSAB99999999")
        assert result is not None
        assert result.beatport_id == 1002
        assert result.bpm == 126


class TestFuzzyMatch:
    async def test_exact_title_match(self, db_session, beatport_tracks):
        result = await fuzzy_match(db_session, "TestArtistGamma", "Pulse Signal")
        assert result is not None
        assert result.beatport_id == 1003

    async def test_remix_disambiguation(self, db_session, beatport_tracks):
        """Must match the remix variant, not the Original Mix."""
        result = await fuzzy_match(
            db_session, "TestArtistAlpha", "Zephyr Dreams", "TestArtistBeta Remix"
        )
        assert result is not None
        assert result.beatport_id == 1002
        assert result.bpm == 126

    async def test_original_mix_match(self, db_session, beatport_tracks):
        """No remix tag should match Original Mix."""
        result = await fuzzy_match(
            db_session, "TestArtistAlpha", "Zephyr Dreams"
        )
        assert result is not None
        assert result.beatport_id == 1001

    async def test_no_match_below_threshold(self, db_session, beatport_tracks):
        result = await fuzzy_match(
            db_session, "TestArtistGamma", "completely different title"
        )
        assert result is None

    async def test_genre_filter(self, db_session, beatport_tracks):
        """Genre filter should narrow results."""
        result = await fuzzy_match(
            db_session, "TestArtistGamma", "Pulse Signal", genre="TestGenreB"
        )
        assert result is not None
        assert result.beatport_id == 1003

    async def test_genre_filter_excludes(self, db_session, beatport_tracks):
        """Wrong genre should exclude the match."""
        result = await fuzzy_match(
            db_session, "TestArtistGamma", "Pulse Signal", genre="WrongGenre"
        )
        assert result is None

    async def test_fuzzy_match_method(self, db_session, beatport_tracks):
        result = await fuzzy_match(db_session, "TestArtistBeta", "Void Echo")
        assert result is not None
        assert result.match_method == "fuzzy"

    async def test_no_candidates(self, db_session, beatport_tracks):
        """Artist not in DB should return None."""
        result = await fuzzy_match(
            db_session, "nonexistent artist zzz", "some track"
        )
        assert result is None
