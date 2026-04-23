from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from scrobblebox.config import settings
from scrobblebox.core.models import Track


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class DisplayState:
    status: str
    updated_at: str
    audio_active: bool
    title: str = ""
    artist: str = ""
    album: str = ""
    artwork_url: str = ""
    duration_seconds: int | None = None
    started_at: str | None = None
    release_id: int | None = None
    side: str | None = None
    position: str | None = None
    message: str = ""

    @classmethod
    def listening(cls) -> "DisplayState":
        return cls(
            status="listening",
            updated_at=utc_now_iso(),
            audio_active=False,
            message="Listening...",
        )

    @classmethod
    def from_track(
        cls,
        track: Track,
        started_at: datetime,
        *,
        audio_active: bool,
        status: str = "playing",
    ) -> "DisplayState":
        return cls(
            status=status,
            updated_at=utc_now_iso(),
            audio_active=audio_active,
            title=track.title,
            artist=track.artist,
            album=track.album,
            artwork_url=track.artwork_url or "",
            duration_seconds=track.duration_seconds,
            started_at=started_at.astimezone(timezone.utc).isoformat(),
            release_id=track.release_id,
            side=track.side,
            position=track.position,
        )


class StateStore:
    def __init__(self, path: Path = settings.now_playing_state_file) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.write(DisplayState.listening())

    def write(self, state: DisplayState) -> None:
        self.path.write_text(json.dumps(asdict(state), indent=2) + "\n", encoding="utf-8")

    def read(self) -> dict:
        if not self.path.exists():
            return asdict(DisplayState.listening())
        return json.loads(self.path.read_text(encoding="utf-8"))
