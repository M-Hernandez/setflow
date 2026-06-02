"""Tests for transition derivation from set_tracks."""

import pytest
from sqlalchemy import select

from app.ingestion.derive_transitions import (
    DerivationResult,
    derive_transitions,
    derive_transitions_for_set,
)
from app.models import DJ, Set, SetTrack, SetType, Track, Transition


@pytest.fixture
async def dj(db_session):
    dj = DJ(name="TestTransDJ", slug="test-trans-dj", genre="Techno")
    db_session.add(dj)
    await db_session.flush()
    return dj


@pytest.fixture
async def tracks(db_session):
    """Three tracks with known BPM/key/subgenre for testing."""
    t1 = Track(
        title="track alpha", artist="test artist", remix=None,
        bpm=122.0, key="A Minor", genre="Techno", subgenre="Melodic Techno",
    )
    t2 = Track(
        title="track beta", artist="test artist", remix=None,
        bpm=126.0, key="E Minor", genre="Techno", subgenre="Melodic Techno",
    )
    t3 = Track(
        title="track gamma", artist="test artist", remix=None,
        bpm=130.0, key="C# Major", genre="Techno", subgenre="Peak Time",
    )
    db_session.add_all([t1, t2, t3])
    await db_session.flush()
    return t1, t2, t3


@pytest.fixture
async def set_with_tracks(db_session, dj, tracks):
    """A set with 3 tracks at consecutive positions with timestamps."""
    t1, t2, t3 = tracks
    s = Set(
        dj_id=dj.id, title="Test Set", set_type=SetType.live,
        is_b2b=False, source="youtube",
    )
    db_session.add(s)
    await db_session.flush()

    st1 = SetTrack(set_id=s.id, track_id=t1.id, position=1, start_time_seconds=0.0)
    st2 = SetTrack(set_id=s.id, track_id=t2.id, position=2, start_time_seconds=360.0)
    st3 = SetTrack(set_id=s.id, track_id=t3.id, position=3, start_time_seconds=720.0)
    db_session.add_all([st1, st2, st3])
    await db_session.flush()
    return s


class TestDeriveTransitionsForSet:
    async def test_creates_transitions(self, db_session, set_with_tracks, tracks):
        """Should create 2 transitions for 3 consecutive tracks."""
        s = set_with_tracks
        created = await derive_transitions_for_set(db_session, s.id)
        assert created == 2

        result = await db_session.execute(
            select(Transition).where(Transition.set_id == s.id).order_by(Transition.position)
        )
        transitions = result.scalars().all()
        assert len(transitions) == 2

    async def test_bpm_delta(self, db_session, set_with_tracks, tracks):
        """BPM delta should be signed (Track B - Track A)."""
        await derive_transitions_for_set(db_session, set_with_tracks.id)

        result = await db_session.execute(
            select(Transition).where(Transition.set_id == set_with_tracks.id)
            .order_by(Transition.position)
        )
        transitions = result.scalars().all()

        # track alpha (122) → track beta (126) = +4
        assert transitions[0].bpm_delta == pytest.approx(4.0)
        # track beta (126) → track gamma (130) = +4
        assert transitions[1].bpm_delta == pytest.approx(4.0)

    async def test_key_relationship(self, db_session, set_with_tracks, tracks):
        """Key relationships should use Camelot wheel logic."""
        await derive_transitions_for_set(db_session, set_with_tracks.id)

        result = await db_session.execute(
            select(Transition).where(Transition.set_id == set_with_tracks.id)
            .order_by(Transition.position)
        )
        transitions = result.scalars().all()

        # A Minor (8A) → E Minor (9A) = adjacent
        assert transitions[0].key_relationship == "adjacent"
        # E Minor (9A) → C# Major (3B) = incompatible
        assert transitions[1].key_relationship == "incompatible"

    async def test_genre_continuity(self, db_session, set_with_tracks, tracks):
        """Genre continuity should compare subgenres."""
        await derive_transitions_for_set(db_session, set_with_tracks.id)

        result = await db_session.execute(
            select(Transition).where(Transition.set_id == set_with_tracks.id)
            .order_by(Transition.position)
        )
        transitions = result.scalars().all()

        # Both "Melodic Techno" → True
        assert transitions[0].genre_continuity is True
        # "Melodic Techno" → "Peak Time" → False
        assert transitions[1].genre_continuity is False

    async def test_track_a_duration(self, db_session, set_with_tracks):
        """Duration should be computed from consecutive timestamps."""
        await derive_transitions_for_set(db_session, set_with_tracks.id)

        result = await db_session.execute(
            select(Transition).where(Transition.set_id == set_with_tracks.id)
            .order_by(Transition.position)
        )
        transitions = result.scalars().all()

        # 360.0 - 0.0 = 360.0
        assert transitions[0].track_a_duration_seconds == pytest.approx(360.0)
        # 720.0 - 360.0 = 360.0
        assert transitions[1].track_a_duration_seconds == pytest.approx(360.0)

    async def test_no_timestamps(self, db_session, dj, tracks):
        """Missing timestamps should result in None duration."""
        t1, t2, _ = tracks
        s = Set(
            dj_id=dj.id, title="No Timestamps", set_type=SetType.live,
            is_b2b=False, source="mixesdb",
        )
        db_session.add(s)
        await db_session.flush()

        st1 = SetTrack(set_id=s.id, track_id=t1.id, position=1, start_time_seconds=None)
        st2 = SetTrack(set_id=s.id, track_id=t2.id, position=2, start_time_seconds=None)
        db_session.add_all([st1, st2])
        await db_session.flush()

        await derive_transitions_for_set(db_session, s.id)

        result = await db_session.execute(
            select(Transition).where(Transition.set_id == s.id)
        )
        t = result.scalar_one()
        assert t.track_a_duration_seconds is None

    async def test_gap_in_positions(self, db_session, dj, tracks):
        """Gaps in position numbers (e.g., 1, 3) should skip the transition."""
        t1, _, t3 = tracks
        s = Set(
            dj_id=dj.id, title="Gap Set", set_type=SetType.live,
            is_b2b=False, source="youtube",
        )
        db_session.add(s)
        await db_session.flush()

        # Position 2 is missing (unresolved track)
        st1 = SetTrack(set_id=s.id, track_id=t1.id, position=1, start_time_seconds=0.0)
        st3 = SetTrack(set_id=s.id, track_id=t3.id, position=3, start_time_seconds=720.0)
        db_session.add_all([st1, st3])
        await db_session.flush()

        created = await derive_transitions_for_set(db_session, s.id)
        assert created == 0

    async def test_single_track_set(self, db_session, dj, tracks):
        """A set with only one track should produce no transitions."""
        t1, _, _ = tracks
        s = Set(
            dj_id=dj.id, title="Solo Set", set_type=SetType.live,
            is_b2b=False, source="youtube",
        )
        db_session.add(s)
        await db_session.flush()

        st1 = SetTrack(set_id=s.id, track_id=t1.id, position=1, start_time_seconds=0.0)
        db_session.add(st1)
        await db_session.flush()

        created = await derive_transitions_for_set(db_session, s.id)
        assert created == 0

    async def test_idempotent_skip(self, db_session, set_with_tracks):
        """Re-running without replace=True should skip and return 0."""
        await derive_transitions_for_set(db_session, set_with_tracks.id)
        created = await derive_transitions_for_set(db_session, set_with_tracks.id)
        assert created == 0

    async def test_idempotent_replace(self, db_session, set_with_tracks):
        """Re-running with replace=True should recreate transitions."""
        await derive_transitions_for_set(db_session, set_with_tracks.id)
        created = await derive_transitions_for_set(
            db_session, set_with_tracks.id, replace=True
        )
        assert created == 2

        # Should still only have 2 transitions (not 4)
        result = await db_session.execute(
            select(Transition).where(Transition.set_id == set_with_tracks.id)
        )
        assert len(result.scalars().all()) == 2

    async def test_missing_bpm(self, db_session, dj):
        """Tracks without BPM should produce None bpm_delta."""
        t1 = Track(title="no bpm a", artist="x", bpm=None, key="A Minor")
        t2 = Track(title="no bpm b", artist="x", bpm=None, key="A Minor")
        db_session.add_all([t1, t2])
        await db_session.flush()

        s = Set(
            dj_id=dj.id, title="No BPM", set_type=SetType.live,
            is_b2b=False, source="youtube",
        )
        db_session.add(s)
        await db_session.flush()

        db_session.add_all([
            SetTrack(set_id=s.id, track_id=t1.id, position=1),
            SetTrack(set_id=s.id, track_id=t2.id, position=2),
        ])
        await db_session.flush()

        await derive_transitions_for_set(db_session, s.id)

        result = await db_session.execute(
            select(Transition).where(Transition.set_id == s.id)
        )
        t = result.scalar_one()
        assert t.bpm_delta is None
        assert t.key_relationship == "same_key"


class TestDeriveTransitions:
    async def test_multiple_sets(self, db_session, dj, tracks):
        """Should process multiple sets."""
        t1, t2, _ = tracks
        sets = []
        for i in range(3):
            s = Set(
                dj_id=dj.id, title=f"Multi Set {i}", set_type=SetType.live,
                is_b2b=False, source="youtube",
            )
            db_session.add(s)
            await db_session.flush()
            db_session.add_all([
                SetTrack(set_id=s.id, track_id=t1.id, position=1),
                SetTrack(set_id=s.id, track_id=t2.id, position=2),
            ])
            await db_session.flush()
            sets.append(s)

        result = await derive_transitions(
            db_session, set_ids=[s.id for s in sets]
        )
        assert result.sets_processed == 3
        assert result.transitions_created == 3

    async def test_genre_continuity_fallback_to_genre(self, db_session, dj):
        """When subgenre is None, should fall back to genre comparison."""
        t1 = Track(
            title="no sub a", artist="x",
            genre="Techno", subgenre=None, bpm=125.0, key="A Minor",
        )
        t2 = Track(
            title="no sub b", artist="x",
            genre="Techno", subgenre=None, bpm=126.0, key="A Minor",
        )
        db_session.add_all([t1, t2])
        await db_session.flush()

        s = Set(
            dj_id=dj.id, title="Genre Fallback", set_type=SetType.live,
            is_b2b=False, source="youtube",
        )
        db_session.add(s)
        await db_session.flush()

        db_session.add_all([
            SetTrack(set_id=s.id, track_id=t1.id, position=1),
            SetTrack(set_id=s.id, track_id=t2.id, position=2),
        ])
        await db_session.flush()

        await derive_transitions_for_set(db_session, s.id)

        result = await db_session.execute(
            select(Transition).where(Transition.set_id == s.id)
        )
        t = result.scalar_one()
        assert t.genre_continuity is True
