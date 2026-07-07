from __future__ import annotations

import asyncio
import logging
import random
import time
import uuid
import wave
from dataclasses import dataclass, field
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


def _boost_for_recognition(samples: np.ndarray) -> np.ndarray:
    arr = np.asarray(samples, dtype=np.float32)
    if arr.size == 0:
        return arr

    peak = float(np.max(np.abs(arr)))
    rms = float(np.sqrt(np.mean(np.square(arr))))
    if peak <= 1e-6:
        return arr

    target_peak = 0.92
    target_rms = 0.12
    gain_peak = target_peak / peak
    gain_rms = (target_rms / rms) if rms > 1e-6 else gain_peak
    gain = min(gain_peak, gain_rms, 40.0)

    if gain > 1.05:
        LOGGER.info(
            "Boosting clip for recognition: rms=%.4f peak=%.4f gain=%.2fx",
            rms,
            peak,
            gain,
        )

    boosted = arr * gain
    return np.clip(boosted, -1.0, 1.0)


def _to_pcm16(samples: np.ndarray) -> np.ndarray:
    boosted = _boost_for_recognition(samples)
    return (boosted * 32767).astype(np.int16)


def _extract_album(track: dict) -> str | None:
    """Best-effort album name from a Shazam track payload.

    Shazam nests album under sections[].metadata[], but that array is often
    missing or empty, so every access is guarded (the old [{}] default only
    covered a missing key, not an empty list, and crashed the service).
    Prefer a metadata entry whose title is "Album"; fall back to the first
    non-empty text value.
    """
    fallback = None
    for section in track.get("sections") or []:
        if not isinstance(section, dict):
            continue
        for item in section.get("metadata") or []:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if not text:
                continue
            if fallback is None:
                fallback = str(text)
            if str(item.get("title", "")).strip().lower() == "album":
                return str(text)
    return fallback


@dataclass(slots=True)
class ShazamRecognizer:
    """Recognize audio clips with ShazamIO."""

    clip_directory: Path = settings.clip_storage_directory
    language: str = "en-US"
    endpoint_country: str = "US"
    recognizer: Recognizer = field(init=False)

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
        LOGGER.info("Shazam response summary: matches=%s track=%s", len(payload.get("matches", [])), bool(payload.get("track")))
        track = payload.get("track")
        if not track:
            LOGGER.info("Shazam did not recognize the latest clip")
            return None

        offset_seconds = 0.0
        matches = payload.get("matches") or []
        match = matches[0] if matches else {}
        if isinstance(match, dict):
            offset_seconds = float(match.get("offset", 0) or 0)

        return RecognitionResult(
            title=str(track.get("title", "")),
            artist=str(track.get("subtitle", "")),
            album=_extract_album(track),
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
