from __future__ import annotations

import logging
from datetime import datetime, timezone

import pylast

from scrobblebox.config import settings
from scrobblebox.core.models import Track


LOGGER = logging.getLogger(__name__)


class LastFMClient:
    """Thin wrapper around pylast for now-playing and scrobble submissions."""

    def __init__(self) -> None:
        self.network = None
        if settings.lastfm_api_key and settings.lastfm_api_secret and settings.lastfm_session_key:
            self.network = pylast.LastFMNetwork(
                api_key=settings.lastfm_api_key,
                api_secret=settings.lastfm_api_secret,
                session_key=settings.lastfm_session_key,
                username=settings.lastfm_username,
            )

    def enabled(self) -> bool:
        return self.network is not None

    def update_now_playing(self, track: Track) -> None:
        if not self.network:
            LOGGER.info("Last.fm credentials missing; skipping now playing update")
            return
        self.network.update_now_playing(
            artist=track.artist,
            title=track.title,
            album=track.album or None,
            duration=track.duration_seconds,
        )
        LOGGER.info("Updated Last.fm now playing: %s - %s", track.artist, track.title)

    def scrobble(self, track: Track, started_at: datetime) -> None:
        if not self.network:
            LOGGER.info("Last.fm credentials missing; skipping scrobble")
            return
        timestamp = int(started_at.replace(tzinfo=timezone.utc).timestamp())
        self.network.scrobble(
            artist=track.artist,
            title=track.title,
            album=track.album or None,
            timestamp=timestamp,
            duration=track.duration_seconds,
        )
        LOGGER.info("Scrobbled to Last.fm: %s - %s", track.artist, track.title)
