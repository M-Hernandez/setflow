"""Tests for the coverage report generator."""

import pytest
from sqlalchemy import select

from app.ingestion.coverage_report import (
    COVERAGE_GATES,
    CoverageReport,
    DJCoverage,
    format_report,
    generate_report,
)
from app.models import DJ, Set, SetTrack, SetType, Track, Transition


@pytest.fixture
async def populated_db(db_session):
    """Create a DJ with sets, tracks, and transitions for coverage testing."""
    dj = DJ(name="CoverTestDJ", slug="cover-test-dj", genre="Techno")
    db_session.add(dj)
    await db_session.flush()

    s = Set(
        dj_id=dj.id, title="Cover Test Set", set_type=SetType.live,
        is_b2b=False, source="youtube",
    )
    db_session.add(s)
    await db_session.flush()

    # 5 tracks: 4 have BPM, 4 have key, 3 have subgenre, 5 have label
    tracks = [
        Track(title="t1", artist="a1", bpm=122.0, key="A Minor", subgenre="Melodic", label="Label1"),
        Track(title="t2", artist="a2", bpm=124.0, key="E Minor", subgenre="Melodic", label="Label2"),
        Track(title="t3", artist="a3", bpm=126.0, key="C Major", subgenre="Peak", label="Label3"),
        Track(title="t4", artist="a4", bpm=128.0, key="G Minor", subgenre=None, label="Label4"),
        Track(title="t5", artist="a5", bpm=None, key=None, subgenre=None, label="Label5"),
    ]
    db_session.add_all(tracks)
    await db_session.flush()

    for i, track in enumerate(tracks):
        st = SetTrack(set_id=s.id, track_id=track.id, position=i + 1)
        db_session.add(st)
    await db_session.flush()

    # Add some transitions
    for i in range(len(tracks) - 1):
        t = Transition(
            set_id=s.id,
            track_a_id=tracks[i].id,
            track_b_id=tracks[i + 1].id,
            position=i + 1,
        )
        db_session.add(t)
    await db_session.flush()

    return dj, s, tracks


class TestGenerateReport:
    async def test_report_structure(self, db_session, populated_db):
        dj, _, tracks = populated_db
        report = await generate_report(db_session)

        assert report.total_sets == 1
        assert report.total_tracks == 5
        assert report.total_unique_tracks == 5
        assert report.total_transitions == 4
        assert len(report.per_dj) == 1

    async def test_coverage_percentages(self, db_session, populated_db):
        report = await generate_report(db_session)

        # 4/5 have BPM = 80%
        assert report.overall_bpm_pct == pytest.approx(0.8)
        # 4/5 have key = 80%
        assert report.overall_key_pct == pytest.approx(0.8)
        # 3/5 have subgenre = 60%
        assert report.overall_subgenre_pct == pytest.approx(0.6)
        # 5/5 have label = 100%
        assert report.overall_label_pct == pytest.approx(1.0)

    async def test_gates_evaluation(self, db_session, populated_db):
        report = await generate_report(db_session)

        # BPM 80% < 90% gate → FAIL
        assert report.gates_passed["bpm"] is False
        # Key 80% < 85% gate → FAIL
        assert report.gates_passed["key"] is False
        # Subgenre 60% < 80% gate → FAIL
        assert report.gates_passed["subgenre"] is False
        # Label 100% >= 90% gate → PASS
        assert report.gates_passed["label"] is True

    async def test_per_dj_stats(self, db_session, populated_db):
        dj, _, _ = populated_db
        report = await generate_report(db_session)

        dj_cov = report.per_dj[0]
        assert dj_cov.dj_name == "CoverTestDJ"
        assert dj_cov.sets == 1
        assert dj_cov.tracks == 5
        assert dj_cov.transitions == 4
        assert dj_cov.set_types == {"live": 1}

    async def test_empty_db(self, db_session):
        report = await generate_report(db_session)
        assert report.total_sets == 0
        assert report.total_tracks == 0
        assert len(report.per_dj) == 0


class TestFormatReport:
    def test_format_includes_key_sections(self):
        report = CoverageReport(
            total_sets=10,
            total_tracks=100,
            total_unique_tracks=80,
            total_transitions=90,
            overall_bpm_pct=0.92,
            overall_key_pct=0.87,
            overall_subgenre_pct=0.75,
            overall_label_pct=0.95,
            gates_passed={"bpm": True, "key": True, "subgenre": False, "label": True},
            per_dj=[
                DJCoverage(
                    dj_name="Test DJ",
                    sets=5, tracks=50, unique_tracks=40, transitions=45,
                    bpm_pct=0.92, key_pct=0.87, subgenre_pct=0.75, label_pct=0.95,
                    set_types={"live": 3, "radio": 2},
                ),
            ],
        )
        text = format_report(report)

        assert "COVERAGE REPORT" in text
        assert "Test DJ" in text
        assert "PASS" in text
        assert "FAIL" in text
        assert "TOTALS" in text
        assert "Sets: 10" in text
