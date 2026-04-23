from __future__ import annotations

from dataclasses import dataclass

from scrobblebox.config import settings


@dataclass(slots=True)
class LyricsService:
    """Scaffold for the now-playing display service."""

    host: str = settings.lyrics_host
    port: int = settings.lyrics_port

    def run(self) -> None:
        print("ScrobbleBox Lyrics")
        print(f"Listening on {self.host}:{self.port}")
        print("Status: scaffold initialized, UI and lyric sync not implemented yet.")


def main() -> None:
    LyricsService().run()


if __name__ == "__main__":
    main()

