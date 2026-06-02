"""Tests for track name canonicalization."""

from app.ingestion.canonicalize import canonicalize, canonicalize_track


class TestCanonicalize:
    def test_lowercase(self):
        assert canonicalize("ARTBAT") == "artbat"

    def test_strip_whitespace(self):
        assert canonicalize("  hello  world  ") == "hello world"

    def test_collapse_spaces(self):
        assert canonicalize("hello   world") == "hello world"

    def test_unicode_normalization(self):
        # é (composed) → e (after stripping combining accent)
        assert canonicalize("café") == "cafe"

    def test_ligatures(self):
        # ﬁ (U+FB01) → fi via NFKD
        assert canonicalize("ﬁnale") == "finale"

    def test_empty_string(self):
        assert canonicalize("") == ""

    def test_already_canonical(self):
        assert canonicalize("adam beyer") == "adam beyer"


class TestCanonicalizeTrack:
    def test_basic(self):
        artist, title, remix = canonicalize_track("ARTBAT", "Return To Oz")
        assert artist == "artbat"
        assert title == "return to oz"
        assert remix is None

    def test_with_remix(self):
        artist, title, remix = canonicalize_track(
            "Monolink", "Return To Oz", "ARTBAT Remix"
        )
        assert artist == "monolink"
        assert title == "return to oz"
        assert remix == "artbat remix"

    def test_none_remix_stays_none(self):
        _, _, remix = canonicalize_track("A", "B", None)
        assert remix is None

    def test_empty_remix_stays_none(self):
        _, _, remix = canonicalize_track("A", "B", "")
        assert remix is None
