"""Pydantic v2 schemas for setflow API representations."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models import SetType


# --- DJ ---


class DJBase(BaseModel):
    name: str
    slug: str
    genre: str | None = None


class DJCreate(DJBase):
    pass


class DJ(DJBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime


# --- Track ---


class TrackBase(BaseModel):
    title: str
    artist: str
    remix: str | None = None
    label: str | None = None
    isrc: str | None = None
    spotify_uri: str | None = None
    beatport_id: int | None = None
    bpm: float | None = None
    key: str | None = None
    genre: str | None = None
    subgenre: str | None = None
    energy: float | None = None


class TrackCreate(TrackBase):
    pass


class Track(TrackBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime


# --- Set ---


class SetBase(BaseModel):
    title: str
    set_type: SetType
    is_b2b: bool = False
    source_url: str | None = None
    source: str | None = None
    venue: str | None = None
    event_date: datetime | None = None
    duration_seconds: int | None = None


class SetCreate(SetBase):
    dj_id: int


class Set(SetBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    dj_id: int
    created_at: datetime


# --- SetTrack ---


class SetTrackBase(BaseModel):
    position: int
    start_time_seconds: float | None = None


class SetTrackCreate(SetTrackBase):
    set_id: int
    track_id: int


class SetTrack(SetTrackBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    set_id: int
    track_id: int
    created_at: datetime


# --- Transition ---


class TransitionBase(BaseModel):
    position: int
    bpm_delta: float | None = None
    key_relationship: str | None = None
    genre_continuity: bool | None = None
    track_a_duration_seconds: float | None = None


class TransitionCreate(TransitionBase):
    set_id: int
    track_a_id: int
    track_b_id: int


class Transition(TransitionBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    set_id: int
    track_a_id: int
    track_b_id: int
    created_at: datetime
