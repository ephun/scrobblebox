from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class Track:
    title: str
    artist: str
    album: str
    side: str | None = None
    position: str | None = None
    duration_seconds: int | None = None


@dataclass(slots=True)
class RecognitionResult:
    title: str
    artist: str
    offset_seconds: int
    recognized_at: datetime = field(default_factory=datetime.utcnow)


@dataclass(slots=True)
class PlaybackWindow:
    audio_started_at: datetime
    continuous_audio_seconds: int = 0
    silence_tolerance_seconds: int = 5

