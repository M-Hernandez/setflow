"""Tests for the Beatport 10M dataset loader."""

import csv
from pathlib import Path

import pytest

from app.ingestion.load_beatport import (
    build_artist_map,
    load_lookup_csv,
    make_sync_url,
    validate_files,
)


class TestMakeSyncUrl:
    def test_converts_asyncpg_to_psycopg2(self):
        url = "postgresql+asyncpg://user:pass@localhost:5432/db"
        assert make_sync_url(url) == "postgresql+psycopg2://user:pass@localhost:5432/db"

    def test_preserves_other_urls(self):
        url = "sqlite:///test.db"
        assert make_sync_url(url) == "sqlite:///test.db"


class TestLoadLookupCsv:
    def test_loads_genre_csv(self, tmp_path):
        csv_path = tmp_path / "bp_genre.csv"
        csv_path.write_text("genre_id,genre_name,song_count\n1,Techno,100\n2,House,200\n")
        result = load_lookup_csv(csv_path, "genre_id", "genre_name")
        assert result == {1: "Techno", 2: "House"}

    def test_loads_key_csv(self, tmp_path):
        csv_path = tmp_path / "bp_key.csv"
        csv_path.write_text("key_id,key_name\n1,A Minor\n2,B Major\n")
        result = load_lookup_csv(csv_path, "key_id", "key_name")
        assert result == {1: "A Minor", 2: "B Major"}


class TestBuildArtistMap:
    def test_joins_multiple_artists(self, tmp_path):
        artist_csv = tmp_path / "bp_artist.csv"
        artist_csv.write_text("artist_id,artist_name,artist_url\n10,ARTBAT,artbat\n20,Anyma,anyma\n")

        artist_track_csv = tmp_path / "bp_artist_track.csv"
        artist_track_csv.write_text(
            "artist_id,track_id,updated_on,is_remixer\n10,100,2023-01-01,f\n20,100,2023-01-01,f\n10,200,2023-01-01,f\n"
        )

        result = build_artist_map(artist_csv, artist_track_csv, chunk_size=10)
        assert result[100] == "ARTBAT, Anyma"
        assert result[200] == "ARTBAT"

    def test_unknown_artist_id(self, tmp_path):
        artist_csv = tmp_path / "bp_artist.csv"
        artist_csv.write_text("artist_id,artist_name,artist_url\n10,ARTBAT,artbat\n")

        artist_track_csv = tmp_path / "bp_artist_track.csv"
        artist_track_csv.write_text("artist_id,track_id,updated_on,is_remixer\n999,100,2023-01-01,f\n")

        result = build_artist_map(artist_csv, artist_track_csv, chunk_size=10)
        assert result[100] == "Unknown"


class TestValidateFiles:
    def test_all_files_present(self, tmp_path):
        for f in [
            "bp_track.csv", "bp_genre.csv", "bp_subgenre.csv",
            "bp_key.csv", "bp_artist.csv", "bp_artist_track.csv",
            "bp_label.csv",
        ]:
            (tmp_path / f).touch()
        assert validate_files(tmp_path) is True

    def test_missing_files(self, tmp_path):
        (tmp_path / "bp_genre.csv").touch()
        assert validate_files(tmp_path) is False
