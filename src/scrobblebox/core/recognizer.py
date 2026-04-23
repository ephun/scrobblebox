from __future__ import annotations

import asyncio
import logging
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from shazamio import Shazam

from scrobblebox.config import settings
from scrobblebox.core.models import RecognitionResult


LOGGER = logging.getLogger(__name__)


def _to_pcm16(samples: np.ndarray) -> np.ndarray:
    clipped = np.clip(samples, -1.0, 1.0)
    return (clipped * 32767).astype(np.int16)


@dataclass(slots=True)
class ShazamRecognizer:
    """Recognize audio clips with ShazamIO."""

    clip_directory: Path = settings.clip_storage_directory

    def __post_init__(self) -> None:
        self.clip_directory.mkdir(parents=True, exist_ok=True)
        self.shazam = Shazam()

    def recognize_samples(self, samples: np.ndarray, samplerate: int) -> RecognitionResult | None:
        clip_path = self.clip_directory / "latest-clip.wav"
        pcm16 = _to_pcm16(samples)
        with wave.open(str(clip_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(samplerate)
            wav_file.writeframes(pcm16.tobytes())

        LOGGER.info("Submitting clip to Shazam: %s", clip_path)
        payload = asyncio.run(self.shazam.recognize(str(clip_path)))
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
