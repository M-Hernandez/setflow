"""Tests for Camelot wheel key compatibility."""

import pytest

from app.ingestion.camelot import key_relationship, to_camelot


class TestToCamelot:
    def test_a_minor(self):
        assert to_camelot("A Minor") == (8, "A")

    def test_c_major(self):
        assert to_camelot("C Major") == (8, "B")

    def test_enharmonic_ab_g_sharp(self):
        """Ab Minor and G# Minor should map to the same Camelot position."""
        assert to_camelot("Ab Minor") == to_camelot("G# Minor") == (1, "A")

    def test_enharmonic_f_sharp_gb(self):
        assert to_camelot("F# Major") == to_camelot("Gb Major") == (2, "B")

    def test_unknown_key(self):
        assert to_camelot("X#") is None

    def test_empty_string(self):
        assert to_camelot("") is None

    def test_all_beatport_keys_mapped(self):
        """All keys from the Beatport dataset should be recognized."""
        beatport_keys = [
            "Ab Major", "Ab Minor", "A Major", "A# Major", "A Minor",
            "A# Minor", "Bb Major", "Bb Minor", "B Major", "B Minor",
            "C Major", "C# Major", "C Minor", "C# Minor", "Db Major",
            "Db Minor", "D Major", "D# Major", "D Minor", "D# Minor",
            "Eb Major", "Eb Minor", "E Major", "E Minor", "F Major",
            "F# Major", "F Minor", "F# Minor", "Gb Major", "Gb Minor",
            "G Major", "G# Major", "G Minor", "G# Minor",
        ]
        for key in beatport_keys:
            assert to_camelot(key) is not None, f"Key '{key}' not mapped"


class TestKeyRelationship:
    def test_same_key(self):
        assert key_relationship("A Minor", "A Minor") == "same_key"

    def test_same_key_enharmonic(self):
        """Ab Minor and G# Minor are the same Camelot position."""
        assert key_relationship("Ab Minor", "G# Minor") == "same_key"

    def test_adjacent_plus_one(self):
        # 8A (A Minor) → 9A (E Minor) = adjacent
        assert key_relationship("A Minor", "E Minor") == "adjacent"

    def test_adjacent_minus_one(self):
        # 8A (A Minor) → 7A (D Minor) = adjacent
        assert key_relationship("A Minor", "D Minor") == "adjacent"

    def test_adjacent_wraps_12_to_1(self):
        # 12B (E Major) → 1B (B Major) = adjacent (wrapping)
        assert key_relationship("E Major", "B Major") == "adjacent"

    def test_adjacent_wraps_1_to_12(self):
        # 1B (B Major) → 12B (E Major) = adjacent (wrapping)
        assert key_relationship("B Major", "E Major") == "adjacent"

    def test_relative_major_minor(self):
        # 8A (A Minor) → 8B (C Major) = relative
        assert key_relationship("A Minor", "C Major") == "relative"

    def test_relative_major_minor_reverse(self):
        assert key_relationship("C Major", "A Minor") == "relative"

    def test_energy_boost(self):
        # 8A (A Minor) → 9B (G Major) = energy boost (+1 and ring switch)
        assert key_relationship("A Minor", "G Major") == "energy_boost"

    def test_incompatible(self):
        # 8A (A Minor) → 3B (C# Major) = incompatible
        assert key_relationship("A Minor", "C# Major") == "incompatible"

    def test_unknown_none_key(self):
        assert key_relationship(None, "A Minor") == "unknown"
        assert key_relationship("A Minor", None) == "unknown"
        assert key_relationship(None, None) == "unknown"

    def test_unknown_bad_key(self):
        assert key_relationship("A Minor", "X# Blah") == "unknown"

    def test_incompatible_same_ring_far_apart(self):
        # 8A (A Minor) → 2A (Eb Minor) = incompatible
        assert key_relationship("A Minor", "Eb Minor") == "incompatible"
