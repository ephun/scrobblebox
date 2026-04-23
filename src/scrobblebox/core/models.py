from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(slots=True)
class ReleaseTrack:
    title: str
    artist: str
    position: str | None = None
    side: str | None = None
    duration_seconds: int | None = None


@dataclass(slots=True)
class Track:
    title: str
    artist: str
    album: str
    lyric_title: str | None = None
    lyric_artist: str | None = None
    lyric_album: str | None = None
    release_id: int | None = None
    artwork_url: str | None = None
    side: str | None = None
    position: str | None = None
    duration_seconds: int | None = None
    release_tracks: list[ReleaseTrack] = field(default_factory=list)


@dataclass(slots=True)
class RecognitionResult:
    title: str
    artist: str
    offset_seconds: int
    album: str | None = None
    shazam_track_id: str | None = None
    raw: dict | None = None
    recognized_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class PlaybackWindow:
    audio_started_at: datetime
    continuous_audio_seconds: int = 0
    silence_tolerance_seconds: int = 5


@dataclass(slots=True)
class PendingScrobble:
    track: Track
    started_at: datetime
    scrobble_at: datetime
    now_playing_sent: bool = False
    scrobbled: bool = False
