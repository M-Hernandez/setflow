"""Camelot wheel key compatibility for DJ transitions.

The Camelot wheel maps musical keys to numbered positions (1-12) with
an inner ring (A = minor) and outer ring (B = major). Compatible
transitions are same position, +/-1 position, or same number across
rings (relative major/minor).

Beatport uses notation like "A Minor", "C# Major", "Bb Minor".
"""

# Camelot wheel mapping: (number, letter) where A=minor, B=major
# Reference: https://mixedinkey.com/camelot-wheel/
_CAMELOT: dict[str, tuple[int, str]] = {
    # Minor keys (A ring)
    "Ab Minor": (1, "A"),
    "G# Minor": (1, "A"),
    "Eb Minor": (2, "A"),
    "D# Minor": (2, "A"),
    "Bb Minor": (3, "A"),
    "A# Minor": (3, "A"),
    "F Minor": (4, "A"),
    "C Minor": (5, "A"),
    "G Minor": (6, "A"),
    "D Minor": (7, "A"),
    "A Minor": (8, "A"),
    "E Minor": (9, "A"),
    "B Minor": (10, "A"),
    "F# Minor": (10, "A"),
    "Gb Minor": (10, "A"),
    "C# Minor": (11, "A"),
    "Db Minor": (11, "A"),
    # Major keys (B ring)
    "B Major": (1, "B"),
    "Cb Major": (1, "B"),
    "F# Major": (2, "B"),
    "Gb Major": (2, "B"),
    "C# Major": (3, "B"),
    "Db Major": (3, "B"),
    "Ab Major": (4, "B"),
    "G# Major": (4, "B"),
    "Eb Major": (5, "B"),
    "D# Major": (5, "B"),
    "Bb Major": (6, "B"),
    "A# Major": (6, "B"),
    "F Major": (7, "B"),
    "C Major": (8, "B"),
    "G Major": (9, "B"),
    "D Major": (10, "B"),
    "A Major": (11, "B"),
    "E Major": (12, "B"),
}


def to_camelot(key: str) -> tuple[int, str] | None:
    """Convert a Beatport key string to a Camelot position.

    Returns (number, ring) tuple or None if key is not recognized.
    """
    return _CAMELOT.get(key)


def key_relationship(key_a: str | None, key_b: str | None) -> str:
    """Classify the harmonic relationship between two keys.

    Returns one of:
    - "same_key" — identical Camelot position
    - "adjacent" — +/-1 on the wheel (same ring)
    - "relative" — same number, opposite ring (relative major/minor)
    - "energy_boost" — +1 number AND switch ring (diagonal move)
    - "incompatible" — none of the above
    - "unknown" — one or both keys missing/unrecognized
    """
    if key_a is None or key_b is None:
        return "unknown"

    pos_a = to_camelot(key_a)
    pos_b = to_camelot(key_b)

    if pos_a is None or pos_b is None:
        return "unknown"

    num_a, ring_a = pos_a
    num_b, ring_b = pos_b

    # Same position = same key (or enharmonic equivalent)
    if num_a == num_b and ring_a == ring_b:
        return "same_key"

    # Same number, different ring = relative major/minor
    if num_a == num_b and ring_a != ring_b:
        return "relative"

    # Adjacent on the wheel (+/-1, wrapping 12→1)
    diff = (num_b - num_a) % 12
    if ring_a == ring_b and diff in (1, 11):
        return "adjacent"

    # Energy boost: +1 number AND switch ring
    if ring_a != ring_b and diff == 1:
        return "energy_boost"

    return "incompatible"
