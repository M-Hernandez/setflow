"""Tests for Phase 1 SQLAlchemy models."""

import pytest
from sqlalchemy import select

from app.models import DJ, Set, SetTrack, SetType, Track, Transition


@pytest.fixture
async def sample_dj(db_session):
    dj = DJ(name="Adam Beyer", slug="adam-beyer", genre="Techno")
    db_session.add(dj)
    await db_session.flush()
    return dj


@pytest.fixture
async def sample_tracks(db_session):
    track_a = Track(title="Drumcode", artist="Adam Beyer", bpm=132.0, key="Am")
    track_b = Track(
        title="Your Mind",
        artist="Adam Beyer",
        remix="Layton Giordani Remix",
        bpm=134.0,
        key="Bm",
    )
    db_session.add_all([track_a, track_b])
    await db_session.flush()
    return track_a, track_b


@pytest.fixture
async def sample_set(db_session, sample_dj):
    s = Set(
        dj_id=sample_dj.id,
        title="Adam Beyer @ Drumcode Festival 2024",
        set_type=SetType.live,
        is_b2b=False,
        source="youtube",
        venue="Drumcode Festival",
    )
    db_session.add(s)
    await db_session.flush()
    return s


class TestDJ:
    async def test_create_and_query(self, db_session, sample_dj):
        result = await db_session.execute(select(DJ).where(DJ.slug == "adam-beyer"))
        dj = result.scalar_one()
        assert dj.name == "Adam Beyer"
        assert dj.genre == "Techno"
        assert dj.created_at is not None

    async def test_unique_name(self, db_session, sample_dj):
        duplicate = DJ(name="Adam Beyer", slug="adam-beyer-2", genre="Techno")
        db_session.add(duplicate)
        with pytest.raises(Exception):
            await db_session.flush()


class TestTrack:
    async def test_create_with_remix(self, db_session, sample_tracks):
        _, track_b = sample_tracks
        result = await db_session.execute(
            select(Track).where(Track.remix == "Layton Giordani Remix")
        )
        track = result.scalar_one()
        assert track.title == "Your Mind"
        assert track.bpm == 134.0

    async def test_unique_track_identity_with_remix(self, db_session):
        t1 = Track(
            title="Revolt", artist="Adam Beyer", remix="Original Mix", bpm=130.0
        )
        t2 = Track(
            title="Revolt", artist="Adam Beyer", remix="Original Mix", bpm=128.0
        )
        db_session.add_all([t1, t2])
        with pytest.raises(Exception):
            await db_session.flush()

    async def test_same_title_different_remix_allowed(self, db_session):
        t1 = Track(title="Revolt", artist="Adam Beyer", remix=None, bpm=130.0)
        t2 = Track(
            title="Revolt", artist="Adam Beyer", remix="ARTBAT Remix", bpm=125.0
        )
        db_session.add_all([t1, t2])
        await db_session.flush()
        assert t1.id != t2.id


class TestSet:
    async def test_create_with_set_type(self, db_session, sample_set):
        result = await db_session.execute(select(Set).where(Set.id == sample_set.id))
        s = result.scalar_one()
        assert s.set_type == SetType.live
        assert s.is_b2b is False
        assert s.source == "youtube"

    async def test_b2b_flag(self, db_session, sample_dj):
        s = Set(
            dj_id=sample_dj.id,
            title="Adam Beyer B2B Cirez D",
            set_type=SetType.live,
            is_b2b=True,
        )
        db_session.add(s)
        await db_session.flush()
        assert s.is_b2b is True


class TestSetTrack:
    async def test_position_ordering(self, db_session, sample_set, sample_tracks):
        track_a, track_b = sample_tracks
        st1 = SetTrack(
            set_id=sample_set.id,
            track_id=track_a.id,
            position=1,
            start_time_seconds=0.0,
        )
        st2 = SetTrack(
            set_id=sample_set.id,
            track_id=track_b.id,
            position=2,
            start_time_seconds=420.0,
        )
        db_session.add_all([st1, st2])
        await db_session.flush()
        assert st1.position == 1
        assert st2.start_time_seconds == 420.0

    async def test_unique_position_per_set(self, db_session, sample_set, sample_tracks):
        track_a, track_b = sample_tracks
        st1 = SetTrack(
            set_id=sample_set.id, track_id=track_a.id, position=1
        )
        st2 = SetTrack(
            set_id=sample_set.id, track_id=track_b.id, position=1
        )
        db_session.add_all([st1, st2])
        with pytest.raises(Exception):
            await db_session.flush()


class TestTransition:
    async def test_create_transition(self, db_session, sample_set, sample_tracks):
        track_a, track_b = sample_tracks
        t = Transition(
            set_id=sample_set.id,
            track_a_id=track_a.id,
            track_b_id=track_b.id,
            position=1,
            bpm_delta=2.0,
            key_relationship="relative_minor",
            genre_continuity=True,
            track_a_duration_seconds=420.0,
        )
        db_session.add(t)
        await db_session.flush()
        assert t.bpm_delta == 2.0
        assert t.key_relationship == "relative_minor"
        assert t.genre_continuity is True

    async def test_foreign_keys(self, db_session, sample_set, sample_tracks):
        track_a, track_b = sample_tracks
        t = Transition(
            set_id=sample_set.id,
            track_a_id=track_a.id,
            track_b_id=track_b.id,
            position=1,
        )
        db_session.add(t)
        await db_session.flush()
        result = await db_session.execute(
            select(Transition).where(Transition.id == t.id)
        )
        transition = result.scalar_one()
        assert transition.set_id == sample_set.id
        assert transition.track_a_id == track_a.id
        assert transition.track_b_id == track_b.id
