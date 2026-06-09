"""Tests for the track resolution pipeline."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.ingestion.deezer_lookup import DeezerMatch
from app.ingestion.discogs_lookup import DiscogsMatch
from app.ingestion.getsongbpm_lookup import GetSongBPMMatch
from app.ingestion.parse_tracklist import ParsedTrack
from app.ingestion.resolve import (
    ResolutionResult,
    UnresolvedTrack,
    resolve_track,
    resolve_tracks,
)
from app.ingestion.spotify_client import SpotifyRateLimitError, SpotifyResult
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

    async def test_no_spotify_falls_through_to_beatport(self, db_session, beatport_data):
        """No Spotify result → still resolves via Beatport fuzzy match."""
        mock = MagicMock()
        mock.search_track = MagicMock(return_value=None)

        parsed = _make_parsed()
        track, unresolved = await resolve_track(db_session, parsed, mock)

        assert track is not None
        assert track.spotify_uri is None
        assert track.bpm == 122.0  # from Beatport fuzzy match
        assert track.key == "Am"
        assert unresolved is None  # fully resolved via Beatport

    async def test_no_spotify_no_beatport_still_saves(self, db_session):
        """No Spotify + no Beatport → track saved with nulls for backfill."""
        mock = MagicMock()
        mock.search_track = MagicMock(return_value=None)

        parsed = _make_parsed(artist="ZZZNoMatchArtist", title="ZZZ Totally Unknown")
        track, unresolved = await resolve_track(db_session, parsed, mock)

        assert track is not None
        assert track.spotify_uri is None
        assert track.bpm is None
        assert track.key is None
        assert unresolved is not None
        assert unresolved.reason == "no_enrichment"

    async def test_rate_limit_degrades_to_beatport(self, db_session, beatport_data):
        """SpotifyRateLimitError → continues with Beatport-only resolution."""
        mock = MagicMock()
        mock.search_track = MagicMock(side_effect=SpotifyRateLimitError(86400))

        parsed = _make_parsed()
        track, unresolved = await resolve_track(db_session, parsed, mock)

        assert track is not None
        assert track.spotify_uri is None
        assert track.bpm == 122.0  # Beatport fuzzy match still works
        assert unresolved is None

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

    async def test_no_enrichment_track_still_saved(self, db_session, dj_and_set):
        """Tracks with no Spotify + no Beatport match still get saved with SetTrack."""
        _, s = dj_and_set
        mock = MagicMock()
        mock.search_track.return_value = None

        parsed_tracks = [_make_parsed(
            position=1, artist="ZZZNoMatchArtist", title="ZZZ Totally Unknown"
        )]
        result = await resolve_tracks(db_session, parsed_tracks, s.id, mock)

        assert result.resolved == 1  # track saved even without enrichment
        assert len(result.unresolved) == 1
        assert result.unresolved[0].reason == "no_enrichment"

        # Verify SetTrack link was created
        rows = await db_session.execute(
            select(SetTrack).where(SetTrack.set_id == s.id)
        )
        assert len(rows.scalars().all()) == 1

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


class TestGapFilling:
    """Tests for Deezer + GetSongBPM gap-filling enrichment."""

    async def test_deezer_fills_bpm_when_beatport_missing(self, db_session):
        """Deezer ISRC lookup fills BPM when Beatport has no match."""
        mock_spotify = MagicMock()
        mock_spotify.is_disabled = False
        mock_spotify.search_track.return_value = _make_spotify_result(
            uri="spotify:track:dz1", isrc="DEEZERTEST01",
        )

        httpx_client = MagicMock()
        parsed = _make_parsed(artist="ZZZDeezerArtist", title="ZZZ Deezer Track")

        with patch(
            "app.ingestion.resolve.deezer_lookup_by_isrc",
            new_callable=AsyncMock,
            return_value=DeezerMatch(deezer_id=12345, bpm=128.0),
        ) as mock_deezer:
            track, unresolved = await resolve_track(
                db_session, parsed, mock_spotify,
                httpx_client=httpx_client,
            )

        mock_deezer.assert_called_once_with(httpx_client, "DEEZERTEST01")
        assert track.bpm == 128.0
        assert track.bpm_source == "deezer"
        assert track.deezer_id == 12345
        # BPM filled → not unresolved
        assert unresolved is None

    async def test_getsongbpm_fills_bpm_and_key(self, db_session):
        """GetSongBPM fills BPM + key when Beatport and Deezer miss."""
        mock_spotify = MagicMock()
        mock_spotify.is_disabled = False
        mock_spotify.search_track.return_value = _make_spotify_result(
            uri="spotify:track:gs1", isrc=None,  # No ISRC → Deezer won't fire
        )

        httpx_client = MagicMock()
        parsed = _make_parsed(artist="ZZZGsBpmArtist", title="ZZZ GsBpm Track")

        with patch(
            "app.ingestion.resolve.getsongbpm_search",
            new_callable=AsyncMock,
            return_value=GetSongBPMMatch(bpm=126.0, key="A Minor"),
        ) as mock_gs:
            track, unresolved = await resolve_track(
                db_session, parsed, mock_spotify,
                httpx_client=httpx_client,
                getsongbpm_api_key="test-key",
            )

        mock_gs.assert_called_once()
        assert track.bpm == 126.0
        assert track.bpm_source == "getsongbpm"
        assert track.key == "A Minor"
        assert track.key_source == "getsongbpm"
        assert unresolved is None

    async def test_getsongbpm_fills_key_when_deezer_filled_bpm(self, db_session):
        """GetSongBPM fills key when Deezer already filled BPM."""
        mock_spotify = MagicMock()
        mock_spotify.is_disabled = False
        mock_spotify.search_track.return_value = _make_spotify_result(
            uri="spotify:track:combo1", isrc="COMBOISRC001",
        )

        httpx_client = MagicMock()
        parsed = _make_parsed(artist="ZZZComboArtist", title="ZZZ Combo Track")

        with patch(
            "app.ingestion.resolve.deezer_lookup_by_isrc",
            new_callable=AsyncMock,
            return_value=DeezerMatch(deezer_id=99999, bpm=130.0),
        ), patch(
            "app.ingestion.resolve.getsongbpm_search",
            new_callable=AsyncMock,
            return_value=GetSongBPMMatch(bpm=131.0, key="C Minor"),
        ) as mock_gs:
            track, _ = await resolve_track(
                db_session, parsed, mock_spotify,
                httpx_client=httpx_client,
                getsongbpm_api_key="test-key",
            )

        # Deezer BPM wins (applied first)
        assert track.bpm == 130.0
        assert track.bpm_source == "deezer"
        # GetSongBPM fills the key gap
        mock_gs.assert_called_once()
        assert track.key == "C Minor"
        assert track.key_source == "getsongbpm"

    async def test_beatport_source_tracking(self, db_session, beatport_data, mock_spotify):
        """Beatport enrichment sets source tracking fields."""
        parsed = _make_parsed()
        track, _ = await resolve_track(db_session, parsed, mock_spotify)

        assert track.bpm_source == "beatport"
        assert track.key_source == "beatport"
        assert track.genre_source == "beatport"
        assert track.subgenre_source == "beatport"
        assert track.label_source == "beatport"

    async def test_no_gap_filling_without_httpx_client(self, db_session):
        """Gap filling is skipped when no httpx_client is provided."""
        mock_spotify = MagicMock()
        mock_spotify.is_disabled = False
        mock_spotify.search_track.return_value = _make_spotify_result(
            uri="spotify:track:nohttpx", isrc="NOHTTPXISR01",
        )

        parsed = _make_parsed(artist="ZZZNoHttpxArtist", title="ZZZ NoHttpx Track")

        with patch(
            "app.ingestion.resolve.deezer_lookup_by_isrc",
            new_callable=AsyncMock,
        ) as mock_deezer:
            track, unresolved = await resolve_track(
                db_session, parsed, mock_spotify,
                httpx_client=None,
            )

        mock_deezer.assert_not_called()
        assert track.bpm is None
        assert unresolved is not None

    async def test_no_getsongbpm_without_api_key(self, db_session):
        """GetSongBPM is skipped when no API key is provided."""
        mock_spotify = MagicMock()
        mock_spotify.is_disabled = False
        mock_spotify.search_track.return_value = _make_spotify_result(
            uri="spotify:track:nokey", isrc=None,
        )

        httpx_client = MagicMock()
        parsed = _make_parsed(artist="ZZZNoKeyArtist", title="ZZZ NoKey Track")

        with patch(
            "app.ingestion.resolve.getsongbpm_search",
            new_callable=AsyncMock,
        ) as mock_gs:
            track, _ = await resolve_track(
                db_session, parsed, mock_spotify,
                httpx_client=httpx_client,
                getsongbpm_api_key=None,
            )

        mock_gs.assert_not_called()

    async def test_deezer_skipped_when_no_isrc(self, db_session):
        """Deezer lookup is skipped when track has no ISRC."""
        mock_spotify = MagicMock()
        mock_spotify.is_disabled = False
        mock_spotify.search_track.return_value = _make_spotify_result(
            uri="spotify:track:noisrc", isrc=None,
        )

        httpx_client = MagicMock()
        parsed = _make_parsed(artist="ZZZNoIsrcArtist", title="ZZZ NoIsrc Track")

        with patch(
            "app.ingestion.resolve.deezer_lookup_by_isrc",
            new_callable=AsyncMock,
        ) as mock_deezer:
            track, _ = await resolve_track(
                db_session, parsed, mock_spotify,
                httpx_client=httpx_client,
            )

        mock_deezer.assert_not_called()

    async def test_beatport_bpm_prevents_deezer_call(self, db_session, beatport_data):
        """When Beatport fills BPM, Deezer is not called."""
        mock_spotify = MagicMock()
        mock_spotify.is_disabled = False
        mock_spotify.search_track.return_value = _make_spotify_result()

        httpx_client = MagicMock()
        parsed = _make_parsed()

        with patch(
            "app.ingestion.resolve.deezer_lookup_by_isrc",
            new_callable=AsyncMock,
        ) as mock_deezer:
            track, _ = await resolve_track(
                db_session, parsed, mock_spotify,
                httpx_client=httpx_client,
            )

        mock_deezer.assert_not_called()
        assert track.bpm == 122.0
        assert track.bpm_source == "beatport"


class TestDiscogsGapFilling:
    """Tests for Discogs genre/subgenre/label gap-filling enrichment."""

    async def test_discogs_fills_genre_and_label(self, db_session):
        """Discogs fills genre/subgenre/label when Beatport has no match."""
        mock_spotify = MagicMock()
        mock_spotify.is_disabled = False
        mock_spotify.search_track.return_value = _make_spotify_result(
            uri="spotify:track:dg1", isrc=None,
        )

        httpx_client = MagicMock()
        parsed = _make_parsed(artist="ZZZDiscogsArtist", title="ZZZ Discogs Track")

        with patch(
            "app.ingestion.resolve.discogs_search_track",
            new_callable=AsyncMock,
            return_value=DiscogsMatch(
                discogs_id=55555,
                styles=["Tech House", "Deep House"],
                label="Innervisions",
                year=2022,
                match_method="track",
            ),
        ) as mock_discogs:
            track, _ = await resolve_track(
                db_session, parsed, mock_spotify,
                httpx_client=httpx_client,
            )

        mock_discogs.assert_called_once()
        assert track.discogs_id == 55555
        assert track.subgenre == "Tech House"
        assert track.subgenre_source == "discogs"
        assert track.genre == "Tech House"
        assert track.genre_source == "discogs"
        assert track.label == "Innervisions"
        assert track.label_source == "discogs"

    async def test_discogs_label_fallback(self, db_session):
        """Label fallback fires when track-level search returns no styles."""
        mock_spotify = MagicMock()
        mock_spotify.is_disabled = False
        mock_spotify.search_track.return_value = _make_spotify_result(
            uri="spotify:track:dglf", isrc=None,
        )

        httpx_client = MagicMock()
        parsed = _make_parsed(artist="ZZZFallbackArtist", title="ZZZ Fallback Track")

        with patch(
            "app.ingestion.resolve.discogs_search_track",
            new_callable=AsyncMock,
            return_value=None,  # Track search fails
        ), patch(
            "app.ingestion.resolve.search_label_styles",
            new_callable=AsyncMock,
            return_value=DiscogsMatch(
                discogs_id=66666,
                styles=["Deep House", "Downtempo"],
                label="Diynamic",
                year=None,
                match_method="label_fallback",
            ),
        ) as mock_label:
            track, _ = await resolve_track(
                db_session, parsed, mock_spotify,
                httpx_client=httpx_client,
            )

        mock_label.assert_called_once()
        assert track.subgenre == "Deep House"
        assert track.genre == "House"
        assert track.label == "Diynamic"

    async def test_discogs_skipped_when_beatport_filled_genre(self, db_session, beatport_data):
        """When Beatport fills genre/subgenre/label, Discogs is not called."""
        mock_spotify = MagicMock()
        mock_spotify.is_disabled = False
        mock_spotify.search_track.return_value = _make_spotify_result()

        httpx_client = MagicMock()
        parsed = _make_parsed()

        with patch(
            "app.ingestion.resolve.discogs_search_track",
            new_callable=AsyncMock,
        ) as mock_discogs:
            track, _ = await resolve_track(
                db_session, parsed, mock_spotify,
                httpx_client=httpx_client,
            )

        mock_discogs.assert_not_called()
        assert track.genre_source == "beatport"

    async def test_discogs_skipped_without_httpx_client(self, db_session):
        """Discogs is skipped when no httpx_client provided."""
        mock_spotify = MagicMock()
        mock_spotify.is_disabled = False
        mock_spotify.search_track.return_value = _make_spotify_result(
            uri="spotify:track:nohttpx2", isrc=None,
        )

        parsed = _make_parsed(artist="ZZZNoHttpx2", title="ZZZ NoHttpx2 Track")

        with patch(
            "app.ingestion.resolve.discogs_search_track",
            new_callable=AsyncMock,
        ) as mock_discogs:
            track, _ = await resolve_track(
                db_session, parsed, mock_spotify,
                httpx_client=None,
            )

        mock_discogs.assert_not_called()

    async def test_discogs_token_passed_through(self, db_session):
        """Discogs token is forwarded to the API calls."""
        mock_spotify = MagicMock()
        mock_spotify.is_disabled = False
        mock_spotify.search_track.return_value = _make_spotify_result(
            uri="spotify:track:dgtoken", isrc=None,
        )

        httpx_client = MagicMock()
        parsed = _make_parsed(artist="ZZZTokenArtist", title="ZZZ Token Track")

        with patch(
            "app.ingestion.resolve.discogs_search_track",
            new_callable=AsyncMock,
            return_value=DiscogsMatch(
                discogs_id=77777,
                styles=["Techno"],
                label="Afterlife",
                year=2023,
                match_method="track",
            ),
        ) as mock_discogs:
            await resolve_track(
                db_session, parsed, mock_spotify,
                httpx_client=httpx_client,
                discogs_token="my-test-token",
            )

        mock_discogs.assert_called_once_with(
            httpx_client, "zzztokenartist", "zzz token track", "my-test-token"
        )
