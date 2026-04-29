from __future__ import annotations

import logging
import queue
import subprocess
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import numpy as np
import sounddevice as sd

from scrobblebox.config import settings


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class ResolvedInput:
    backend: str
    device: int | None = None
    alsa_device: str | None = None


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


def _rank_alsa_device(name: str) -> int:
    lowered = name.lower()
    if lowered.startswith("plughw:"):
        return 0
    if lowered.startswith("hw:"):
        return 1
    if lowered.startswith("default:"):
        return 2
    if lowered.startswith("sysdefault:"):
        return 3
    if lowered.startswith("front:"):
        return 4
    return 5


def resolve_alsa_input_device(device_name: str) -> str | None:
    """Resolve an ALSA capture device by matching `arecord -L` entries."""
    normalized = device_name.strip().lower()
    if not normalized:
        return "default"

    try:
        result = subprocess.run(
            ["arecord", "-L"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None

    devices: list[tuple[str, str]] = []
    current_name: str | None = None
    description: list[str] = []
    for raw_line in result.stdout.splitlines():
        if not raw_line.strip():
            continue
        if raw_line[:1].isspace():
            if current_name:
                description.append(raw_line.strip())
            continue
        if current_name:
            devices.append((current_name, " ".join(description)))
        current_name = raw_line.strip()
        description = []
    if current_name:
        devices.append((current_name, " ".join(description)))

    matches = [
        (name, desc)
        for name, desc in devices
        if normalized in name.lower() or normalized in desc.lower()
    ]
    if not matches:
        return None

    matches.sort(key=lambda item: (_rank_alsa_device(item[0]), len(item[0])))
    return matches[0][0]


def resolve_input_backend(device_name: str) -> ResolvedInput:
    try:
        return ResolvedInput(backend="sounddevice", device=resolve_input_device(device_name))
    except RuntimeError:
        alsa_device = resolve_alsa_input_device(device_name)
        if alsa_device:
            LOGGER.warning(
                "Falling back to ALSA capture via arecord for %r using device %s",
                device_name,
                alsa_device,
            )
            return ResolvedInput(backend="arecord", alsa_device=alsa_device)
        raise


def _read_exact(stream, size: int) -> bytes:
    buffer = bytearray()
    while len(buffer) < size:
        chunk = stream.read(size - len(buffer))
        if not chunk:
            break
        buffer.extend(chunk)
    return bytes(buffer)


@dataclass(slots=True)
class AudioChunk:
    samples: np.ndarray
    started_at: datetime
    ended_at: datetime
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
    backend: str = field(init=False, default="sounddevice")
    alsa_device: str | None = field(init=False, default=None)
    blocksize: int = field(init=False)
    _stream: sd.InputStream | None = field(init=False, default=None)
    _next_chunk_started_at: datetime | None = field(init=False, default=None)
    _arecord_process: subprocess.Popen[bytes] | None = field(init=False, default=None)
    _reader_thread: threading.Thread | None = field(init=False, default=None)
    _stop_event: threading.Event = field(init=False, default_factory=threading.Event)

    def __post_init__(self) -> None:
        resolved = resolve_input_backend(self.device_name)
        self.backend = resolved.backend
        self.device = resolved.device
        self.alsa_device = resolved.alsa_device
        self.blocksize = max(1, int(self.samplerate * self.block_seconds))

    def __enter__(self) -> "AudioCapture":
        LOGGER.info("Opening audio input stream via %s", self.backend)
        self._next_chunk_started_at = None
        self._stop_event.clear()
        if self.backend == "arecord":
            self._start_arecord()
        else:
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
        self._stop_event.set()
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        if self._arecord_process is not None:
            self._arecord_process.terminate()
            self._arecord_process.wait(timeout=5)
            self._arecord_process = None
        if self._reader_thread is not None:
            self._reader_thread.join(timeout=5)
            self._reader_thread = None
        self._next_chunk_started_at = None

    def _callback(self, indata, frames, time, status) -> None:
        if status:
            LOGGER.warning("Audio callback status: %s", status)

        mono = np.mean(indata.copy(), axis=1)
        rms = float(np.sqrt(np.mean(np.square(mono))))
        frame_duration = timedelta(seconds=frames / self.samplerate)
        if self._next_chunk_started_at is None:
            started_at = datetime.now(timezone.utc) - frame_duration
        else:
            started_at = self._next_chunk_started_at
        ended_at = started_at + frame_duration
        self._next_chunk_started_at = ended_at
        self.block_queue.put(
            AudioChunk(
                samples=mono,
                started_at=started_at,
                ended_at=ended_at,
                recorded_at=ended_at,
                rms=rms,
            )
        )

    def _start_arecord(self) -> None:
        if not self.alsa_device:
            raise RuntimeError("ALSA fallback requested without a resolved ALSA device")

        command = [
            "arecord",
            "-q",
            "-D",
            self.alsa_device,
            "-f",
            "S16_LE",
            "-c",
            str(self.channels),
            "-r",
            str(self.samplerate),
            "-t",
            "raw",
            "-",
        ]
        self._arecord_process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._reader_thread = threading.Thread(
            target=self._read_arecord_loop,
            name="scrobblebox-arecord-reader",
            daemon=True,
        )
        self._reader_thread.start()

    def _read_arecord_loop(self) -> None:
        if self._arecord_process is None or self._arecord_process.stdout is None:
            return

        bytes_per_frame = self.channels * 2
        block_bytes = self.blocksize * bytes_per_frame
        while not self._stop_event.is_set():
            payload = _read_exact(self._arecord_process.stdout, block_bytes)
            if len(payload) < block_bytes:
                break
            samples_i16 = np.frombuffer(payload, dtype=np.int16)
            if self.channels > 1:
                shaped = samples_i16.reshape(-1, self.channels).astype(np.float32) / 32768.0
                mono = np.mean(shaped, axis=1)
            else:
                mono = samples_i16.astype(np.float32) / 32768.0
            rms = float(np.sqrt(np.mean(np.square(mono))))
            frame_duration = timedelta(seconds=len(mono) / self.samplerate)
            if self._next_chunk_started_at is None:
                started_at = datetime.now(timezone.utc) - frame_duration
            else:
                started_at = self._next_chunk_started_at
            ended_at = started_at + frame_duration
            self._next_chunk_started_at = ended_at
            self.block_queue.put(
                AudioChunk(
                    samples=mono,
                    started_at=started_at,
                    ended_at=ended_at,
                    recorded_at=ended_at,
                    rms=rms,
                )
            )

        if self._arecord_process.poll() not in (None, 0) and self._arecord_process.stderr is not None:
            stderr_output = self._arecord_process.stderr.read().decode("utf-8", errors="ignore").strip()
            if stderr_output:
                LOGGER.warning("arecord exited unexpectedly: %s", stderr_output)


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
        while self._chunks and self._chunks[0].ended_at < cutoff:
            self._chunks.popleft()

    def recent_clip(self) -> AudioClip | None:
        """Return the most recent clip-sized mono buffer with clip timing metadata."""
        if not self._chunks:
            return None

        clip_samples = self.samplerate * self.clip_seconds
        parts: list[np.ndarray] = []
        selected_chunks: list[AudioChunk] = []
        collected = 0
        for chunk in reversed(self._chunks):
            parts.append(chunk.samples)
            selected_chunks.append(chunk)
            collected += len(chunk.samples)
            if collected >= clip_samples:
                break

        if collected < clip_samples:
            return None

        ordered_chunks = list(reversed(selected_chunks))
        combined = np.concatenate(list(reversed(parts)))
        clip = combined[-clip_samples:]
        trimmed_prefix_samples = len(combined) - clip_samples
        first_chunk = ordered_chunks[0]
        started_at = first_chunk.started_at + timedelta(seconds=trimmed_prefix_samples / self.samplerate)
        ended_at = started_at + timedelta(seconds=len(clip) / self.samplerate)
        return AudioClip(samples=clip, started_at=started_at, ended_at=ended_at)
