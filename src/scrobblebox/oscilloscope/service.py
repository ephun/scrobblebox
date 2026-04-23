from __future__ import annotations

from dataclasses import dataclass

from scrobblebox.config import settings


@dataclass(slots=True)
class OscilloscopeService:
    """Scaffold for smart-plug based oscilloscope power control."""

    device_alias: str = settings.kasa_device_alias
    idle_minutes: int = settings.oscilloscope_idle_minutes

    def run(self) -> None:
        print("ScrobbleBox Oscilloscope")
        print(f"Target device: {self.device_alias}")
        print(f"Idle timeout: {self.idle_minutes} minutes")
        print("Status: scaffold initialized, smart plug integration not implemented yet.")


def main() -> None:
    OscilloscopeService().run()


if __name__ == "__main__":
    main()

