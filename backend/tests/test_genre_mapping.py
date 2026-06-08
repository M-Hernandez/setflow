"""Tests for Discogs style → Beatport subgenre mapping."""

from app.ingestion.genre_mapping import map_styles_to_subgenre


def test_direct_house_mapping():
    assert map_styles_to_subgenre(["Deep House"]) == ("Deep House", "House")


def test_direct_techno_mapping():
    assert map_styles_to_subgenre(["Techno"]) == (
        "Techno (Peak Time / Driving)", "Techno"
    )


def test_tech_house():
    assert map_styles_to_subgenre(["Tech House"]) == ("Tech House", "Tech House")


def test_progressive_house():
    assert map_styles_to_subgenre(["Progressive House"]) == (
        "Progressive House", "Progressive House"
    )


def test_downtempo_maps_to_organic():
    assert map_styles_to_subgenre(["Downtempo"]) == (
        "Organic House / Downtempo", "Organic House / Downtempo"
    )


def test_melodic_via_dub_techno():
    assert map_styles_to_subgenre(["Dub Techno"]) == (
        "Melodic House & Techno", "Melodic House & Techno"
    )


def test_first_match_wins():
    """When multiple styles match, the first one in the list wins."""
    sub, genre = map_styles_to_subgenre(["Deep House", "Tech House"])
    assert sub == "Deep House"
    assert genre == "House"


def test_skips_unknown_styles():
    """Unknown styles are skipped, first known style wins."""
    sub, genre = map_styles_to_subgenre(["IDM", "Experimental", "Ambient"])
    assert sub == "Organic House / Downtempo"


def test_no_match_returns_none():
    assert map_styles_to_subgenre(["IDM", "Drum n Bass"]) == (None, None)


def test_empty_list_returns_none():
    assert map_styles_to_subgenre([]) == (None, None)


def test_minimal_maps_to_deep_tech():
    assert map_styles_to_subgenre(["Minimal"]) == (
        "Minimal / Deep Tech", "Techno"
    )
