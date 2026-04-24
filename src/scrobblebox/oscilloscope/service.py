from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from kasa import Discover

from scrobblebox.config import settings
from scrobblebox.lyrics.display import parse_iso_utc
from scrobblebox.lyrics.state import StateStore


logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

LOGGER = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class OscilloscopeService:
    """Manage the oscilloscope smart plug based on shared playback state."""

    device_alias: str = settings.kasa_device_alias
    kasa_username: str = settings.kasa_username
    kasa_password: str = settings.kasa_password
    idle_minutes: int = settings.oscilloscope_idle_minutes
    poll_seconds: int = settings.oscilloscope_poll_seconds

    def run(self) -> None:
        LOGGER.info(
            "Starting oscilloscope automation for alias=%s idle_minutes=%s poll_seconds=%s",
            self.device_alias,
            self.idle_minutes,
            self.poll_seconds,
        )
        asyncio.run(self._serve_forever())

    async def _serve_forever(self) -> None:
        state_store = StateStore()
        last_active_at: datetime | None = None
        cached_host: str | None = None
        cached_is_on: bool | None = None
        warned_missing = False
        idle_timeout = timedelta(minutes=self.idle_minutes)
        active_state_max_age = timedelta(
            seconds=max(
                45,
                settings.recognition_cooldown_seconds
                + settings.shazam_clip_seconds
                + settings.silence_tolerance_seconds,
            )
        )

        while True:
            try:
                state = state_store.read()
                now = utc_now()
                updated_at = parse_iso_utc(state.get("updated_at"))
                audio_active = bool(state.get("audio_active"))
                state_is_fresh = bool(updated_at and now - updated_at <= active_state_max_age)
                if audio_active and state_is_fresh:
                    last_active_at = now

                should_be_on = bool(last_active_at and now - last_active_at < idle_timeout)
                device = await self._resolve_device(cached_host)
                if device is None:
                    if not warned_missing:
                        LOGGER.warning(
                            "Could not find Kasa device with alias %r on the network",
                            self.device_alias,
                        )
                        warned_missing = True
                    await asyncio.sleep(self.poll_seconds)
                    continue

                warned_missing = False
                cached_host = device.host
                is_on = self._relay_state(device)
                cached_is_on = is_on

                if should_be_on and not is_on:
                    LOGGER.info("Turning oscilloscope plug on")
                    await device.turn_on()
                    cached_is_on = True
                elif not should_be_on and is_on:
                    LOGGER.info("Turning oscilloscope plug off")
                    await device.turn_off()
                    cached_is_on = False
                else:
                    LOGGER.debug(
                        "Oscilloscope state unchanged: should_be_on=%s is_on=%s fresh=%s audio_active=%s",
                        should_be_on,
                        cached_is_on,
                        state_is_fresh,
                        audio_active,
                    )
            except KeyboardInterrupt:
                raise
            except Exception:
                LOGGER.exception("Oscilloscope control loop failed")

            await asyncio.sleep(self.poll_seconds)

    async def _resolve_device(self, cached_host: str | None):
        if cached_host:
            device = await self._discover_single(cached_host)
            if device is not None:
                return device

        discover_kwargs = self._discover_kwargs()
        devices = await Discover.discover(discovery_timeout=5, **discover_kwargs)
        for host, device in devices.items():
            if getattr(device, "alias", None) == self.device_alias:
                LOGGER.info("Resolved oscilloscope plug alias %r at %s", self.device_alias, host)
                return device
        return None

    async def _discover_single(self, host: str):
        try:
            device = await Discover.discover_single(host, **self._discover_kwargs())
            if getattr(device, "alias", None) == self.device_alias:
                return device
            LOGGER.warning(
                "Cached Kasa host %s no longer matches alias %r (saw %r)",
                host,
                self.device_alias,
                getattr(device, "alias", None),
            )
        except Exception:
            LOGGER.debug("Failed to refresh cached Kasa host %s", host, exc_info=True)
        return None

    def _discover_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if self.kasa_username:
            kwargs["username"] = self.kasa_username
        if self.kasa_password:
            kwargs["password"] = self.kasa_password
        return kwargs

    @staticmethod
    def _relay_state(device) -> bool:
        sys_info = getattr(device, "sys_info", {}) or {}
        relay_state = sys_info.get("relay_state")
        if relay_state is None:
            return bool(getattr(device, "is_on", False))
        return bool(relay_state)


def main() -> None:
    OscilloscopeService().run()


if __name__ == "__main__":
    main()
