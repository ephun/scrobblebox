from __future__ import annotations

from dataclasses import dataclass

from scrobblebox.config import settings


@dataclass(slots=True)
class CoreService:
    """High-level scaffold for the daemon-like playback engine."""

    clip_seconds: int = settings.shazam_clip_seconds
    silence_tolerance_seconds: int = settings.silence_tolerance_seconds

    def run(self) -> None:
        """Start the core service loop."""
        print("ScrobbleBox Core")
        print(f"Input device: {settings.audio_input_device}")
        print(f"Clip length: {self.clip_seconds}s")
        print("Status: scaffold initialized, recognition loop not implemented yet.")


def main() -> None:
    CoreService().run()


if __name__ == "__main__":
    main()

