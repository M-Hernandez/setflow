"""Discogs style → Beatport subgenre mapping.

Simple direct mapping: each Discogs style maps to at most one Beatport subgenre
within our 6 target genres. No label-based heuristics — just 1:1 style matches.

Target Beatport genres:
  - Tech House
  - Melodic House & Techno
  - House
  - Progressive House
  - Organic House / Downtempo
  - Techno
"""

# Discogs style tag (exact string) → Beatport subgenre
DISCOGS_TO_BEATPORT: dict[str, str] = {
    # House family
    "House": "House",
    "Deep House": "Deep House",
    "Acid House": "Acid House",
    "Tribal House": "Tribal House",
    "Euro House": "Funky / Groove / Jackin' House",
    "Garage House": "Funky / Groove / Jackin' House",
    "Hip-House": "House",
    # Tech House
    "Tech House": "Tech House",
    "Electro House": "Electro House",
    # Progressive House
    "Progressive House": "Progressive House",
    # Melodic House & Techno — Discogs doesn't have this as a style,
    # so we map adjacent styles that commonly fall in this bucket
    "Dub Techno": "Melodic House & Techno",
    # Techno family
    "Techno": "Techno (Peak Time / Driving)",
    "Minimal Techno": "Minimal / Deep Tech",
    "Minimal": "Minimal / Deep Tech",
    "Acid Techno": "Techno (Peak Time / Driving)",
    "Hard Techno": "Hard Techno",
    # Organic House / Downtempo
    "Downtempo": "Organic House / Downtempo",
    "Ambient": "Organic House / Downtempo",
    "Trip Hop": "Organic House / Downtempo",
    "Leftfield": "Organic House / Downtempo",
    # Crossover styles that have a reasonable primary mapping
    "Breaks": "Breaks",
    "Trance": "Trance (Main Floor)",
    "Progressive Trance": "Trance (Main Floor)",
}

# Reverse lookup: Beatport subgenre → parent Beatport genre
SUBGENRE_TO_GENRE: dict[str, str] = {
    "House": "House",
    "Deep House": "House",
    "Acid House": "House",
    "Tribal House": "House",
    "Funky / Groove / Jackin' House": "House",
    "Tech House": "Tech House",
    "Electro House": "Electro House",
    "Progressive House": "Progressive House",
    "Melodic House & Techno": "Melodic House & Techno",
    "Techno (Peak Time / Driving)": "Techno",
    "Minimal / Deep Tech": "Techno",
    "Hard Techno": "Techno",
    "Organic House / Downtempo": "Organic House / Downtempo",
    "Breaks": "Breaks",
    "Trance (Main Floor)": "Trance",
}


def map_styles_to_subgenre(styles: list[str]) -> tuple[str | None, str | None]:
    """Map a list of Discogs styles to the best Beatport (subgenre, genre) pair.

    Returns the first matching (subgenre, genre) tuple, or (None, None)
    if no style maps to a known Beatport subgenre.
    """
    for style in styles:
        subgenre = DISCOGS_TO_BEATPORT.get(style)
        if subgenre:
            genre = SUBGENRE_TO_GENRE.get(subgenre)
            return subgenre, genre
    return None, None
