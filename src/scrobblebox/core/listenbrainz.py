from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

from scrobblebox.config import settings
from scrobblebox.core.models import Track

LOGGER = logging.getLogger(__name__)

class ListenBrainzClient:
    """Client for submitting now-playing and scrobble payloads to ListenBrainz."""

    def __init__(self) -> None:
        self.url = settings.listenbrainz_url.rstrip("/") if settings.listenbrainz_url else ""
        self.token = settings.listenbrainz_token

    def enabled(self) -> bool:
        return bool(self.url and self.token)

    def _submit(self, listen_type: str, track: Track, started_at: datetime | None = None) -> None:
        if not self.enabled():
            return

        payload = {
            "listen_type": listen_type,
            "payload": [
                {
                    "track_metadata": {
                        "artist_name": track.artist,
                        "track_name": track.title,
                    }
                }
            ]
        }

        if track.album:
            payload["payload"][0]["track_metadata"]["release_name"] = track.album

        if listen_type == "single" and started_at:
            payload["payload"][0]["listened_at"] = int(started_at.replace(tzinfo=timezone.utc).timestamp())

        endpoint = f"{self.url}/submit-listens" if self.url.endswith("/1") else f"{self.url}/1/submit-listens"
        
        headers = {
            "Authorization": f"Token {self.token}",
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(endpoint, json=payload, headers=headers, timeout=10)
            response.raise_for_status()
        except requests.RequestException as e:
            LOGGER.error("ListenBrainz API error (%s): %s", listen_type, e)

    def update_now_playing(self, track: Track) -> None:
        if not self.enabled():
            LOGGER.info("ListenBrainz configuration missing; skipping now playing update")
            return
        self._submit("playing_now", track)
        LOGGER.info("Updated ListenBrainz now playing: %s - %s", track.artist, track.title)

    def scrobble(self, track: Track, started_at: datetime) -> None:
        if not self.enabled():
            LOGGER.info("ListenBrainz configuration missing; skipping scrobble")
            return
        self._submit("single", track, started_at)
        LOGGER.info("Scrobbled to ListenBrainz: %s - %s", track.artist, track.title)
