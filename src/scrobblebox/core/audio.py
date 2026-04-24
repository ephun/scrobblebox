from __future__ import annotations

import logging
import queue
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import numpy as np
import sounddevice as sd

from scrobblebox.config import settings


LOGGER = logging.getLogger(__name__)


def resolve_input_device(device_name: str) -> int | None:
    """Resolve an input device by substring match, or return None for the default."""
    normalized = device_name.strip().lower()
    if not normalized or normalized == "default":
        return None

    devices = sd.query_devices()
    for index, device in enumerate(devices):
        if device["max_input_channels"] <= 0:
            continue
        if normalized in str(device["name"]).lower():
            return index

    available = [
        f"{index}: {device['name']}"
        for index, device in enumerate(devices)
        if device["max_input_channels"] > 0
    ]
    raise RuntimeError(
        f"Audio input device {device_name!r} was not found. Available inputs: {available}"
    )


@dataclass(slots=True)
class AudioChunk:
    samples: np.ndarray
    recorded_at: datetime
    rms: float


@dataclass(slots=True)
class AudioClip:
    samples: np.ndarray
    started_at: datetime
    ended_at: datetime


@dataclass(slots=True)
class AudioCapture:
    """Capture audio blocks from the configured input device."""

    samplerate: int = settings.audio_sample_rate
    channels: int = settings.audio_channels
    block_seconds: float = settings.audio_block_seconds
    device_name: str = settings.audio_input_device
    block_queue: queue.Queue[AudioChunk] = field(default_factory=queue.Queue)
    device: int | None = field(init=False)
    blocksize: int = field(init=False)
    _stream: sd.InputStream | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        self.device = resolve_input_device(self.device_name)
        self.blocksize = max(1, int(self.samplerate * self.block_seconds))

    def __enter__(self) -> "AudioCapture":
        LOGGER.info("Opening audio input stream")
        self._stream = sd.InputStream(
            samplerate=self.samplerate,
            channels=self.channels,
            blocksize=self.blocksize,
            dtype="float32",
            device=self.device,
            callback=self._callback,
        )
        self._stream.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def _callback(self, indata, frames, time, status) -> None:
        if status:
            LOGGER.warning("Audio callback status: %s", status)

        mono = np.mean(indata.copy(), axis=1)
        rms = float(np.sqrt(np.mean(np.square(mono))))
        self.block_queue.put(
            AudioChunk(samples=mono, recorded_at=datetime.now(timezone.utc), rms=rms)
        )


@dataclass(slots=True)
class RollingAudioBuffer:
    """Retain a rolling window of recent audio samples for clip extraction."""

    samplerate: int
    clip_seconds: int
    max_seconds: int | None = None
    _chunks: deque[AudioChunk] = field(default_factory=deque)

    def __post_init__(self) -> None:
        self.max_seconds = self.max_seconds or max(self.clip_seconds * 2, self.clip_seconds + 10)

    def append(self, chunk: AudioChunk) -> None:
        self._chunks.append(chunk)
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=self.max_seconds)
        while self._chunks and self._chunks[0].recorded_at < cutoff:
            self._chunks.popleft()

    def recent_clip(self) -> AudioClip | None:
        """Return the most recent clip-sized mono buffer with clip timing metadata."""
        if not self._chunks:
            return None

        clip_samples = self.samplerate * self.clip_seconds
        parts: list[np.ndarray] = []
        collected = 0
        for chunk in reversed(self._chunks):
            parts.append(chunk.samples)
            collected += len(chunk.samples)
            if collected >= clip_samples:
                break

        if collected < clip_samples:
            return None

        combined = np.concatenate(list(reversed(parts)))
        clip = combined[-clip_samples:]
        ended_at = self._chunks[-1].recorded_at
        started_at = ended_at - timedelta(seconds=len(clip) / self.samplerate)
        return AudioClip(samples=clip, started_at=started_at, ended_at=ended_at)
