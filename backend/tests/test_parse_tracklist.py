"""Tests for the pure-function tracklist parser."""

import pytest

from app.ingestion.parse_tracklist import (
    ParsedTrack,
    parse_track_line,
    parse_tracklist,
    timestamp_to_seconds,
)


class TestTimestampToSeconds:
    def test_zero(self):
        assert timestamp_to_seconds("0:00") == 0.0

    def test_minutes_seconds(self):
        assert timestamp_to_seconds("5:32") == 332.0

    def test_max_minutes(self):
        assert timestamp_to_seconds("59:59") == 3599.0

    def test_one_hour(self):
        assert timestamp_to_seconds("1:00:00") == 3600.0

    def test_hours_minutes_seconds(self):
        assert timestamp_to_seconds("1:15:30") == 4530.0

    def test_single_digit_minutes(self):
        assert timestamp_to_seconds("2:30") == 150.0

    def test_invalid_format(self):
        with pytest.raises(ValueError):
            timestamp_to_seconds("invalid")


class TestParseTrackLine:
    def test_standard_format(self):
        result = parse_track_line("00:00 Artist - Track Title", 1)
        assert result is not None
        assert result.position == 1
        assert result.timestamp == "00:00"
        assert result.timestamp_seconds == 0.0
        assert result.artist == "Artist"
        assert result.title == "Track Title"
        assert result.remix is None
        assert result.label is None

    def test_with_remix(self):
        result = parse_track_line("05:32 Artist - Track (ARTBAT Remix)", 2)
        assert result is not None
        assert result.artist == "Artist"
        assert result.title == "Track"
        assert result.remix == "ARTBAT Remix"

    def test_with_label(self):
        result = parse_track_line("10:00 Artist - Track [Drumcode]", 3)
        assert result is not None
        assert result.title == "Track"
        assert result.label == "Drumcode"

    def test_with_remix_and_label(self):
        result = parse_track_line(
            "15:00 Artist - Track (Dub Mix) [Afterlife]", 4
        )
        assert result is not None
        assert result.title == "Track"
        assert result.remix == "Dub Mix"
        assert result.label == "Afterlife"

    def test_multiple_artists(self):
        result = parse_track_line(
            "20:00 Artist A & Artist B - Track", 5
        )
        assert result is not None
        assert result.artist == "Artist A & Artist B"
        assert result.title == "Track"

    def test_hhmmss_timestamp(self):
        result = parse_track_line("1:15:30 Artist - Track", 6)
        assert result is not None
        assert result.timestamp == "1:15:30"
        assert result.timestamp_seconds == 4530.0

    def test_non_tracklist_line_returns_none(self):
        assert parse_track_line("Subscribe to my channel!", 1) is None

    def test_empty_line_returns_none(self):
        assert parse_track_line("", 1) is None

    def test_url_returns_none(self):
        assert parse_track_line("https://youtube.com/watch?v=abc", 1) is None

    def test_feat_is_not_remix(self):
        result = parse_track_line(
            "05:00 Artist - Track (feat. Someone)", 1
        )
        assert result is not None
        assert result.remix is None
        assert "feat. Someone" in result.title

    def test_original_mix_is_remix(self):
        result = parse_track_line(
            "05:00 Artist - Track (Original Mix)", 1
        )
        assert result is not None
        assert result.remix == "Original Mix"
        assert result.title == "Track"

    def test_numbered_prefix(self):
        result = parse_track_line("1. 00:00 Artist - Track", 1)
        assert result is not None
        assert result.artist == "Artist"
        assert result.title == "Track"

    def test_remix_tag_variations(self):
        variations = [
            ("(ARTBAT Remix)", "ARTBAT Remix"),
            ("(Club Rmx)", "Club Rmx"),
            ("(Extended Mix)", "Extended Mix"),
            ("(Radio Edit)", "Radio Edit"),
            ("(Solomun Rework)", "Solomun Rework"),
            ("(Deep Dub)", "Deep Dub"),
            ("(Festival Bootleg)", "Festival Bootleg"),
            ("(Acoustic Version)", "Acoustic Version"),
            ("(VIP)", "VIP"),
            ("(Festival Flip)", "Festival Flip"),
            ("(Anton Tumas Remake)", "Anton Tumas Remake"),
        ]
        for tag, expected in variations:
            result = parse_track_line(f"00:00 Artist - Track {tag}", 1)
            assert result is not None, f"Failed for tag: {tag}"
            assert result.remix == expected, f"Failed for tag: {tag}"

    def test_no_separator_returns_none(self):
        assert parse_track_line("00:00 Just a title no separator", 1) is None

    def test_dash_in_title(self):
        result = parse_track_line("05:00 Artist - Re-Birth", 1)
        assert result is not None
        assert result.artist == "Artist"
        assert result.title == "Re-Birth"

    def test_whitespace_handling(self):
        result = parse_track_line("  00:00  Artist  -  Track Title  ", 1)
        assert result is not None
        assert result.artist == "Artist"
        assert result.title == "Track Title"


class TestParseTracklist:
    def test_full_description(self):
        description = """Boiler Room x Drumcode Festival 2024

Follow us on Instagram: @boilerroom

Tracklist:

00:00 Adam Beyer - Drumcode 001
05:32 Layton Giordani - New Generation (ARTBAT Remix) [Drumcode]
12:45 Enrico Sangiuliano - Symbiosis
1:15:30 ANNA - Hidden Beauties [Afterlife]

Subscribe for more sets!
https://youtube.com/boilerroom"""

        tracks = parse_tracklist(description)
        assert len(tracks) == 4
        assert tracks[0].position == 1
        assert tracks[0].artist == "Adam Beyer"
        assert tracks[1].remix == "ARTBAT Remix"
        assert tracks[1].label == "Drumcode"
        assert tracks[2].artist == "Enrico Sangiuliano"
        assert tracks[3].timestamp_seconds == 4530.0

    def test_empty_description(self):
        assert parse_tracklist("") == []

    def test_no_tracklist_description(self):
        description = """Check out my latest DJ set!
Follow me on Instagram: @dj_cool
Subscribe for more content!
https://soundcloud.com/dj_cool"""
        assert parse_tracklist(description) == []

    def test_positions_are_sequential(self):
        description = """00:00 Artist A - Track 1
05:00 Artist B - Track 2
10:00 Artist C - Track 3"""
        tracks = parse_tracklist(description)
        assert [t.position for t in tracks] == [1, 2, 3]
