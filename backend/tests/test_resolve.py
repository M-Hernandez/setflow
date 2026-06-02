"""Tests for the track resolution pipeline."""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from app.ingestion.parse_tracklist import ParsedTrack
from app.ingestion.resolve import (
    ResolutionResult,
    UnresolvedTrack,
    resolve_track,
    resolve_tracks,
)
from app.ingestion.spotify_client import SpotifyResult
from app.models import DJ, BeatportTrack, Set, SetTrack, SetType, Track


def _make_parsed(
    position=1, artist="TestResolveArtist", title="Test Resolve Track",
    remix=None, timestamp="0:00",
):
    return ParsedTrack(
        position=position,
        timestamp=timestamp,
        timestamp_seconds=0.0,
        artist=artist,
        title=title,
        remix=remix,
    )


def _make_spotify_result(
    uri="spotify:track:abc123", isrc="TSTRESOL0001",
    name="Test Resolve Track", artist="TestResolveArtist",
):
    return SpotifyResult(
        spotify_uri=uri,
        isrc=isrc,
        duration_ms=420000,
        name=name,
        artist=artist,
    )


@pytest.fixture
async def dj_and_set(db_session):
    dj = DJ(name="Test DJ", slug="test-dj", genre="Techno")
    db_session.add(dj)
    await db_session.flush()
    s = Set(
        dj_id=dj.id,
        title="Test Set",
        set_type=SetType.live,
        is_b2b=False,
        source="youtube",
    )
    db_session.add(s)
    await db_session.flush()
    return dj, s


@pytest.fixture
async def beatport_data(db_session):
    bp = BeatportTrack(
        id=9901,
        name="Test Resolve Track",
        mix_name="Original Mix",
        artist="TestResolveArtist",
        label="TestResolveLabel",
        isrc="TSTRESOL0001",
        bpm=122,
        key="Am",
        genre="TestResolveGenre",
        subgenre="TestResolveSub",
    )
    db_session.add(bp)
    await db_session.flush()
    return bp


@pytest.fixture
def mock_spotify():
    mock = MagicMock()
    mock.search_track = MagicMock(return_value=_make_spotify_result())
    return mock


class TestResolveTrack:
    async def test_full_resolution(self, db_session, beatport_data, mock_spotify):
        """Track found on Spotify + matched on Beatport via ISRC."""
        parsed = _make_parsed()
        track, unresolved = await resolve_track(db_session, parsed, mock_spotify)

        assert track is not None
        assert track.spotify_uri == "spotify:track:abc123"
        assert track.isrc == "TSTRESOL0001"
        assert track.bpm == 122.0
        assert track.key == "Am"
        assert track.genre == "TestResolveGenre"
        assert unresolved is None

    async def test_no_spotify_match(self, db_session, beatport_data):
        """No Spotify result → unresolved with reason."""
        mock = MagicMock()
        mock.search_track = MagicMock(return_value=None)

        parsed = _make_parsed()
        track, unresolved = await resolve_track(db_session, parsed, mock)

        assert track is None
        assert unresolved is not None
        assert unresolved.reason == "no_spotify_match"

    async def test_spotify_but_no_beatport(self, db_session, mock_spotify):
        """Spotify found but no Beatport match → partially resolved."""
        mock_spotify.search_track.return_value = _make_spotify_result(
            uri="spotify:track:zzz999", isrc="UNKNOWNISRC1",
            name="Fake Track", artist="ZZZNoArtistMatch",
        )

        parsed = _make_parsed(artist="ZZZNoArtistMatch", title="Fake Track")
        track, unresolved = await resolve_track(db_session, parsed, mock_spotify)

        assert track is not None
        assert track.spotify_uri is not None
        assert unresolved is not None
        assert unresolved.reason == "no_beatport_match"

    async def test_deduplication_by_identity(self, db_session, beatport_data, mock_spotify):
        """Existing track with same (title, artist, remix) should be reused."""
        existing = Track(
            title="test resolve track",
            artist="testresolveartist",
            remix=None,
            spotify_uri="spotify:track:existing",
        )
        db_session.add(existing)
        await db_session.flush()

        parsed = _make_parsed()
        track, _ = await resolve_track(db_session, parsed, mock_spotify)

        assert track.id == existing.id

    async def test_deduplication_by_isrc(self, db_session, beatport_data, mock_spotify):
        """Existing track with same ISRC should be reused even if name differs."""
        existing = Track(
            title="test resolve track (radio edit)",
            artist="testresolveartist alt",
            remix=None,
            isrc="TSTRESOL0001",
        )
        db_session.add(existing)
        await db_session.flush()

        parsed = _make_parsed()
        track, _ = await resolve_track(db_session, parsed, mock_spotify)

        assert track.id == existing.id

    async def test_deduplication_by_spotify_uri(self, db_session, mock_spotify):
        """Existing track with same Spotify URI should be reused."""
        existing = Track(
            title="different title",
            artist="different artist",
            remix=None,
            spotify_uri="spotify:track:abc123",
        )
        db_session.add(existing)
        await db_session.flush()

        parsed = _make_parsed()
        track, _ = await resolve_track(db_session, parsed, mock_spotify)

        assert track.id == existing.id

    async def test_canonicalization_applied(self, db_session, beatport_data, mock_spotify):
        """Input with mixed case/unicode should be canonicalized."""
        parsed = _make_parsed(artist="TestResolveArtist", title="Test Resolve Track")
        track, _ = await resolve_track(db_session, parsed, mock_spotify)

        assert track.artist == "testresolveartist"
        assert track.title == "test resolve track"


class TestResolveTracks:
    async def test_full_pipeline(self, db_session, dj_and_set, beatport_data, mock_spotify):
        """Full pipeline: resolve multiple tracks and create SetTrack rows."""
        _, s = dj_and_set
        parsed_tracks = [
            _make_parsed(position=1),
            _make_parsed(position=2, artist="ZZZNoMatchArtist", title="ZZZ No Match"),
        ]
        # Second track won't match Beatport (no ISRC match, no fuzzy match)
        def side_effect(artist, title, remix=None):
            if "ZZZNoMatch" in artist:
                return _make_spotify_result(
                    uri="spotify:track:nomatch", isrc=None,
                    name="ZZZ No Match", artist="ZZZNoMatchArtist",
                )
            return _make_spotify_result()

        mock_spotify.search_track.side_effect = side_effect

        result = await resolve_tracks(db_session, parsed_tracks, s.id, mock_spotify)

        assert result.resolved == 2
        assert len(result.unresolved) == 1  # Beyer has no Beatport match
        assert result.unresolved[0].reason == "no_beatport_match"

        # Verify SetTrack rows
        rows = await db_session.execute(
            select(SetTrack).where(SetTrack.set_id == s.id).order_by(SetTrack.position)
        )
        set_tracks = rows.scalars().all()
        assert len(set_tracks) == 2
        assert set_tracks[0].position == 1
        assert set_tracks[1].position == 2

    async def test_unresolved_track_logged(self, db_session, dj_and_set):
        """Tracks with no Spotify match should appear in unresolved list."""
        _, s = dj_and_set
        mock = MagicMock()
        mock.search_track.return_value = None

        parsed_tracks = [_make_parsed(position=1)]
        result = await resolve_tracks(db_session, parsed_tracks, s.id, mock)

        assert result.resolved == 0
        assert len(result.unresolved) == 1
        assert result.unresolved[0].reason == "no_spotify_match"

    async def test_timestamp_linked(self, db_session, dj_and_set, beatport_data, mock_spotify):
        """SetTrack should include start_time_seconds from parsed track."""
        _, s = dj_and_set
        parsed = ParsedTrack(
            position=1,
            timestamp="15:30",
            timestamp_seconds=930.0,
            artist="TestResolveArtist",
            title="Test Resolve Track",
        )

        result = await resolve_tracks(db_session, [parsed], s.id, mock_spotify)
        assert result.resolved == 1

        row = await db_session.execute(
            select(SetTrack).where(SetTrack.set_id == s.id)
        )
        set_track = row.scalar_one()
        assert set_track.start_time_seconds == 930.0

    async def test_negative_timestamp_stored_as_none(
        self, db_session, dj_and_set, beatport_data, mock_spotify
    ):
        """MixesDB unknown timestamps (-1.0) should be stored as None."""
        _, s = dj_and_set
        parsed = ParsedTrack(
            position=1,
            timestamp="??",
            timestamp_seconds=-1.0,
            artist="TestResolveArtist",
            title="Test Resolve Track",
        )

        await resolve_tracks(db_session, [parsed], s.id, mock_spotify)

        row = await db_session.execute(
            select(SetTrack).where(SetTrack.set_id == s.id)
        )
        set_track = row.scalar_one()
        assert set_track.start_time_seconds is None
