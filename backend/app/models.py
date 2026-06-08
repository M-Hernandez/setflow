"""SQLAlchemy ORM models for setflow Phase 1 data ingestion."""

import enum
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class SetType(enum.Enum):
    live = "live"
    radio = "radio"
    mixtape = "mixtape"
    guest_mix = "guest_mix"


class DJ(Base):
    __tablename__ = "djs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    genre: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    sets: Mapped[list["Set"]] = relationship(back_populates="dj")


class Set(Base):
    __tablename__ = "sets"

    id: Mapped[int] = mapped_column(primary_key=True)
    dj_id: Mapped[int] = mapped_column(ForeignKey("djs.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    set_type: Mapped[SetType] = mapped_column(
        Enum(SetType, name="set_type_enum", native_enum=True), nullable=False
    )
    is_b2b: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(50))  # youtube, mixesdb, mixcloud
    venue: Mapped[str | None] = mapped_column(String(500))
    event_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    dj: Mapped["DJ"] = relationship(back_populates="sets")
    set_tracks: Mapped[list["SetTrack"]] = relationship(
        back_populates="set", cascade="all, delete-orphan"
    )
    transitions: Mapped[list["Transition"]] = relationship(
        back_populates="set", cascade="all, delete-orphan"
    )


class Track(Base):
    __tablename__ = "tracks"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    artist: Mapped[str] = mapped_column(String(500), nullable=False)
    remix: Mapped[str | None] = mapped_column(String(500))
    label: Mapped[str | None] = mapped_column(String(500))
    isrc: Mapped[str | None] = mapped_column(String(12), index=True)
    spotify_uri: Mapped[str | None] = mapped_column(String(100), index=True)
    beatport_id: Mapped[int | None] = mapped_column(Integer, index=True)
    bpm: Mapped[float | None] = mapped_column(Float)
    key: Mapped[str | None] = mapped_column(String(10))
    genre: Mapped[str | None] = mapped_column(String(255))
    subgenre: Mapped[str | None] = mapped_column(String(255))
    energy: Mapped[float | None] = mapped_column(Float)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024))

    # Enrichment source tracking — which API/dataset provided each field
    bpm_source: Mapped[str | None] = mapped_column(String(20))
    key_source: Mapped[str | None] = mapped_column(String(20))
    genre_source: Mapped[str | None] = mapped_column(String(20))
    subgenre_source: Mapped[str | None] = mapped_column(String(20))
    label_source: Mapped[str | None] = mapped_column(String(20))

    # External IDs from enrichment sources
    deezer_id: Mapped[int | None] = mapped_column(Integer)
    discogs_id: Mapped[int | None] = mapped_column(Integer)
    musicbrainz_id: Mapped[str | None] = mapped_column(String(36))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("title", "artist", "remix", name="uq_track_identity"),
    )

    set_tracks: Mapped[list["SetTrack"]] = relationship(back_populates="track")


class SetTrack(Base):
    __tablename__ = "set_tracks"

    id: Mapped[int] = mapped_column(primary_key=True)
    set_id: Mapped[int] = mapped_column(ForeignKey("sets.id"), nullable=False)
    track_id: Mapped[int] = mapped_column(ForeignKey("tracks.id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time_seconds: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("set_id", "position", name="uq_set_position"),
    )

    set: Mapped["Set"] = relationship(back_populates="set_tracks")
    track: Mapped["Track"] = relationship(back_populates="set_tracks")


class Transition(Base):
    __tablename__ = "transitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    set_id: Mapped[int] = mapped_column(ForeignKey("sets.id"), nullable=False)
    track_a_id: Mapped[int] = mapped_column(ForeignKey("tracks.id"), nullable=False)
    track_b_id: Mapped[int] = mapped_column(ForeignKey("tracks.id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    bpm_delta: Mapped[float | None] = mapped_column(Float)
    key_relationship: Mapped[str | None] = mapped_column(String(50))
    genre_continuity: Mapped[bool | None] = mapped_column(Boolean)
    track_a_duration_seconds: Mapped[float | None] = mapped_column(Float)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("set_id", "position", name="uq_transition_position"),
    )

    set: Mapped["Set"] = relationship(back_populates="transitions")
    track_a: Mapped["Track"] = relationship(foreign_keys=[track_a_id])
    track_b: Mapped["Track"] = relationship(foreign_keys=[track_b_id])


class BeatportTrack(Base):
    """Denormalized reference table from the Beatport 10M Kaggle dataset.

    Used by the track resolution pipeline to enrich parsed tracklists
    with BPM, key, genre, subgenre, and label data.
    """

    __tablename__ = "beatport_tracks"

    id: Mapped[int] = mapped_column(primary_key=True)  # Beatport track ID
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    mix_name: Mapped[str | None] = mapped_column(String(500))
    artist: Mapped[str] = mapped_column(String(1000), nullable=False)
    label: Mapped[str | None] = mapped_column(String(500))
    isrc: Mapped[str | None] = mapped_column(String(12), index=True)
    bpm: Mapped[int | None] = mapped_column(Integer)
    key: Mapped[str | None] = mapped_column(String(10))
    genre: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    subgenre: Mapped[str | None] = mapped_column(String(255))
    release_date: Mapped[str | None] = mapped_column(String(10))
