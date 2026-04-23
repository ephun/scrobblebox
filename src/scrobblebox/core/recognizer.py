from __future__ import annotations

import asyncio
import logging
import random
import time
import uuid
import wave
from dataclasses import dataclass
from pathlib import Path

import aiohttp
import numpy as np
from shazamio_core import Recognizer, SearchParams

from scrobblebox.config import settings
from scrobblebox.core.models import RecognitionResult


LOGGER = logging.getLogger(__name__)
SEARCH_URL = (
    "https://amp.shazam.com/discovery/v5/{language}/{country}/{device}/-/tag/"
    "{uuid_1}/{uuid_2}?sync=true&webv3=true&sampling=true&connected=&"
    "shazamapiversion=v3&sharehub=true&hubv5minorversion=v5.1&hidelb=true&video=v3"
)
SEARCH_DEVICES = ("iphone", "android", "web")


def _to_pcm16(samples: np.ndarray) -> np.ndarray:
    clipped = np.clip(samples, -1.0, 1.0)
    return (clipped * 32767).astype(np.int16)


@dataclass(slots=True)
class ShazamRecognizer:
    """Recognize audio clips with ShazamIO."""

    clip_directory: Path = settings.clip_storage_directory
    language: str = "en-US"
    endpoint_country: str = "US"

    def __post_init__(self) -> None:
        self.clip_directory.mkdir(parents=True, exist_ok=True)
        self.recognizer = Recognizer(segment_duration_seconds=settings.shazam_clip_seconds)

    def recognize_samples(self, samples: np.ndarray, samplerate: int) -> RecognitionResult | None:
        clip_path = self.clip_directory / "latest-clip.wav"
        pcm16 = _to_pcm16(samples)
        with wave.open(str(clip_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(samplerate)
            wav_file.writeframes(pcm16.tobytes())

        LOGGER.info("Submitting clip to Shazam: %s", clip_path)
        payload = asyncio.run(self._recognize_file(clip_path))
        track = payload.get("track")
        if not track:
            LOGGER.info("Shazam did not recognize the latest clip")
            return None

        offset_seconds = 0
        match = payload.get("matches", [{}])[0]
        if isinstance(match, dict):
            offset_seconds = int(float(match.get("offset", 0) or 0))

        return RecognitionResult(
            title=str(track.get("title", "")),
            artist=str(track.get("subtitle", "")),
            album=str(track.get("sections", [{}])[0].get("metadata", [{}])[0].get("text", ""))
            if track.get("sections")
            else None,
            offset_seconds=offset_seconds,
            shazam_track_id=str(track.get("key", "")) or None,
            raw=payload,
        )

    async def _recognize_file(self, clip_path: Path) -> dict:
        signature = await self.recognizer.recognize_path(
            value=str(clip_path),
            options=SearchParams(segment_duration_seconds=settings.shazam_clip_seconds),
        )
        payload = {
            "timezone": time.tzname[0] if time.tzname else "UTC",
            "signature": {
                "uri": signature.signature.uri,
                "samplems": signature.signature.samples,
            },
            "timestamp": signature.timestamp,
            "context": {},
            "geolocation": {},
        }
        url = SEARCH_URL.format(
            language=self.language,
            country=self.endpoint_country,
            device=random.choice(SEARCH_DEVICES),
            uuid_1=str(uuid.uuid4()).upper(),
            uuid_2=str(uuid.uuid4()).upper(),
        )
        headers = {
            "X-Shazam-Platform": "IPHONE",
            "X-Shazam-AppVersion": "14.1.0",
            "Accept": "*/*",
            "Accept-Language": self.language,
            "Accept-Encoding": "gzip, deflate",
            "User-Agent": "ScrobbleBox/0.1",
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.post(url, json=payload) as response:
                response.raise_for_status()
                return await response.json()
