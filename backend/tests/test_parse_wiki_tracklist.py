"""Tests for the MixesDB wiki markup tracklist parser."""

from datetime import date

import pytest

from app.ingestion.parse_wiki_tracklist import (
    MixesDBSetMetadata,
    WikiTrackSection,
    _wiki_timestamp_to_seconds,
    classify_set_type,
    flatten_tracks,
    parse_page_title,
    parse_wiki_track_line,
    parse_wiki_tracklist,
)


class TestWikiTimestampToSeconds:
    def test_minutes_only_zero(self):
        assert _wiki_timestamp_to_seconds("00") == 0.0

    def test_minutes_only(self):
        assert _wiki_timestamp_to_seconds("36") == 2160.0

    def test_mm_ss(self):
        assert _wiki_timestamp_to_seconds("50:24") == 3024.0

    def test_hh_mm_ss(self):
        assert _wiki_timestamp_to_seconds("1:15:30") == 4530.0

    def test_unknown(self):
        assert _wiki_timestamp_to_seconds("??") == -1.0

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            _wiki_timestamp_to_seconds("a:b:c:d")


class TestParseWikiTrackLine:
    def test_with_minutes_timestamp(self):
        result = parse_wiki_track_line(
            "# [12] The Chemical Brothers - Hey Boy, Hey Girl (ARTBAT Remix) [Virgin/Positiva]",
            1,
        )
        assert result is not None
        assert result.timestamp == "12"
        assert result.timestamp_seconds == 720.0
        assert result.artist == "The Chemical Brothers"
        assert result.title == "Hey Boy, Hey Girl"
        assert result.remix == "ARTBAT Remix"
        assert result.label == "Virgin/Positiva"

    def test_with_mm_ss_timestamp(self):
        result = parse_wiki_track_line(
            "# [00:08] Alle Farben & Graham Candy - Flowers [Warner Bros.]", 1
        )
        assert result is not None
        assert result.timestamp == "00:08"
        assert result.timestamp_seconds == 8.0

    def test_no_timestamp(self):
        result = parse_wiki_track_line(
            "# AndThen - Salsa (Tom Staar Remix) [Adesso - AM26R]", 1
        )
        assert result is not None
        assert result.timestamp == ""
        assert result.timestamp_seconds == -1.0
        assert result.artist == "AndThen"
        assert result.title == "Salsa"
        assert result.remix == "Tom Staar Remix"
        assert result.label == "Adesso - AM26R"

    def test_unknown_timestamp(self):
        result = parse_wiki_track_line(
            "# [??] Watzgood - Superfreak [Parade]", 1
        )
        assert result is not None
        assert result.timestamp == "??"
        assert result.timestamp_seconds == -1.0
        assert result.artist == "Watzgood"
        assert result.label == "Parade"

    def test_no_remix_no_label(self):
        result = parse_wiki_track_line(
            "# [36] The Temper Trap - Sweet Disposition", 1
        )
        assert result is not None
        assert result.remix is None
        assert result.label is None

    def test_non_track_line_returns_none(self):
        assert parse_wiki_track_line("Some random text", 1) is None

    def test_empty_line_returns_none(self):
        assert parse_wiki_track_line("", 1) is None

    def test_section_header_returns_none(self):
        assert parse_wiki_track_line(";ARTBAT", 1) is None

    def test_no_separator_returns_none(self):
        assert parse_wiki_track_line("# [00] Just a title no dash", 1) is None

    def test_position_preserved(self):
        result = parse_wiki_track_line(
            "# [00] Artist - Track", 7
        )
        assert result is not None
        assert result.position == 7

    def test_extended_mix(self):
        result = parse_wiki_track_line(
            "# [48] Deadmau5 - Some Chords (Extended Mix) [Mau5trap]", 1
        )
        assert result is not None
        assert result.remix == "Extended Mix"
        assert result.title == "Some Chords"
        assert result.label == "Mau5trap"

    def test_feat_is_not_remix(self):
        result = parse_wiki_track_line(
            "# [00] Gotye Feat. Kimbra - Somebody That I Used To Know", 1
        )
        assert result is not None
        assert result.remix is None
        assert result.artist == "Gotye Feat. Kimbra"


class TestParseWikiTracklist:
    def test_single_dj(self):
        wikitext = """# [00] ARTBAT & Armin van Buuren - Take Off [Armada/Upperground]
# [12] The Chemical Brothers - Hey Boy, Hey Girl (ARTBAT Remix) [Virgin/Positiva]
# [36] The Temper Trap - Sweet Disposition (ARTBAT Remix)"""
        sections = parse_wiki_tracklist(wikitext)
        assert len(sections) == 1
        assert sections[0].dj_name is None
        assert len(sections[0].tracks) == 3
        assert sections[0].tracks[0].position == 1
        assert sections[0].tracks[2].position == 3

    def test_multi_dj_sections(self):
        wikitext = """;Moguai
# Bruno Furlan - Bongoloco [Hot Creations]
# KREAM - So Hï (Extended Mix) [Musical Freedom]

;ARTBAT
# [00] ARTBAT & Armin van Buuren - Take Off [Armada/Upperground]
# [12] The Chemical Brothers - Hey Boy, Hey Girl (ARTBAT Remix) [Virgin/Positiva]"""
        sections = parse_wiki_tracklist(wikitext)
        assert len(sections) == 2
        assert sections[0].dj_name == "Moguai"
        assert len(sections[0].tracks) == 2
        assert sections[1].dj_name == "ARTBAT"
        assert len(sections[1].tracks) == 2
        # Each section restarts position numbering
        assert sections[0].tracks[0].position == 1
        assert sections[1].tracks[0].position == 1

    def test_empty_wikitext(self):
        assert parse_wiki_tracklist("") == []

    def test_no_tracks_in_wikitext(self):
        wikitext = """== External links ==
Some random wiki content
[[Category:2024]]"""
        assert parse_wiki_tracklist(wikitext) == []

    def test_section_header_with_wiki_link(self):
        wikitext = """;Moguai
# Bruno Furlan - Bongoloco [Hot Creations]
;Alle Farben = [[2023-06-23 - Alle Farben - SLAM! MixMarathon]]
# Basement Jaxx - Red Alert [Atlantic Jaxx]"""
        sections = parse_wiki_tracklist(wikitext)
        assert len(sections) == 2
        assert sections[0].dj_name == "Moguai"
        assert sections[1].dj_name == "Alle Farben"

    def test_ignores_non_track_lines(self):
        wikitext = """== Tracklist ==
Some preamble text
# [00] Artist A - Track 1
Random comment
# [05] Artist B - Track 2
[[Category:House]]"""
        sections = parse_wiki_tracklist(wikitext)
        assert len(sections) == 1
        assert len(sections[0].tracks) == 2


class TestFlattenTracks:
    def test_flatten_renumbers_positions(self):
        wikitext = """;DJ A
# Artist A1 - Title One [Label]
# Artist A2 - Title Two [Label]
;DJ B
# Artist B1 - Title Three [Label]"""
        sections = parse_wiki_tracklist(wikitext)
        flat = flatten_tracks(sections)
        assert len(flat) == 3
        assert [t.position for t in flat] == [1, 2, 3]
        assert flat[0].artist == "Artist A1"
        assert flat[2].artist == "Artist B1"

    def test_flatten_single_section(self):
        sections = [
            WikiTrackSection(dj_name=None, tracks=[]),
        ]
        assert flatten_tracks(sections) == []

    def test_flatten_empty(self):
        assert flatten_tracks([]) == []


class TestParsePageTitle:
    def test_standard_with_venue(self):
        m = parse_page_title(
            "2024-09-28 - ARTBAT @ Cercle, Chateau De Fontainebleau, Fontainebleau"
        )
        assert m.event_date == date(2024, 9, 28)
        assert m.dj_names == ["ARTBAT"]
        assert m.venue == "Cercle, Chateau De Fontainebleau, Fontainebleau"
        assert m.is_b2b is False
        assert m.event_name is None

    def test_multi_dj_radio_show(self):
        m = parse_page_title(
            "2023-07-01 - Moguai, ARTBAT, Alle Farben - 1LIVE DJ Session"
        )
        assert m.event_date == date(2023, 7, 1)
        assert m.dj_names == ["Moguai", "ARTBAT", "Alle Farben"]
        assert m.event_name == "1LIVE DJ Session"
        assert m.venue is None

    def test_b2b(self):
        m = parse_page_title(
            "2025-02-21 - Armin van Buuren b2b ARTBAT @ A State Of Trance, Ahoy, Rotterdam"
        )
        assert m.is_b2b is True
        assert "Armin van Buuren" in m.dj_names
        assert "ARTBAT" in m.dj_names
        assert m.venue == "A State Of Trance, Ahoy, Rotterdam"

    def test_no_date(self):
        m = parse_page_title("ARTBAT @ Cercle")
        assert m.event_date is None
        assert m.dj_names == ["ARTBAT @ Cercle"]

    def test_single_dj_no_venue(self):
        m = parse_page_title("2024-01-15 - Adam Beyer")
        assert m.event_date == date(2024, 1, 15)
        assert m.dj_names == ["Adam Beyer"]
        assert m.venue is None
        assert m.event_name is None


class TestClassifySetType:
    def test_radio_show(self):
        assert classify_set_type(["Category:Radio show", "Category:2024"]) == "radio"

    def test_podcast(self):
        assert classify_set_type(["Category:Podcast"]) == "radio"

    def test_guest_mix(self):
        assert classify_set_type(["Category:Guest mix", "Category:Radio show"]) == "guest_mix"

    def test_mixtape(self):
        assert classify_set_type(["Category:Mixtape"]) == "mixtape"

    def test_default_live(self):
        assert classify_set_type(["Category:2024", "Category:ARTBAT"]) == "live"

    def test_empty_categories(self):
        assert classify_set_type([]) == "live"

    def test_essential_mix(self):
        assert classify_set_type(["Category:Essential Mix"]) == "radio"
