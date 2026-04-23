from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from queue import Empty

from scrobblebox.config import settings
from scrobblebox.core.audio import AudioCapture, AudioChunk, RollingAudioBuffer
from scrobblebox.core.discogs import DiscogsClient
from scrobblebox.core.lastfm import LastFMClient
from scrobblebox.core.models import PendingScrobble
from scrobblebox.core.recognizer import ShazamRecognizer
from scrobblebox.core.runtime import build_pending_scrobble, same_track


logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class CoreService:
    """Daemon that detects playback, recognizes clips, validates, and scrobbles."""

    clip_seconds: int = settings.shazam_clip_seconds
    silence_tolerance_seconds: int = settings.silence_tolerance_seconds
    silence_threshold: float = settings.silence_threshold
    recognition_cooldown_seconds: int = settings.recognition_cooldown_seconds

    def run(self) -> None:
        LOGGER.info("Starting ScrobbleBox Core")
        LOGGER.info(
            "Audio device=%s sample_rate=%s channels=%s clip_seconds=%s",
            settings.audio_input_device or "default",
            settings.audio_sample_rate,
            settings.audio_channels,
            self.clip_seconds,
        )
        recognizer = ShazamRecognizer()
        discogs = DiscogsClient()
        lastfm = LastFMClient()
        buffer = RollingAudioBuffer(
            samplerate=settings.audio_sample_rate,
            clip_seconds=self.clip_seconds,
        )

        audio_active = False
        last_audio_at: datetime | None = None
        last_recognition_at = datetime.min
        pending: PendingScrobble | None = None

        with AudioCapture() as capture:
            while True:
                try:
                    chunk = capture.block_queue.get(timeout=1)
                except Empty:
                    self._flush_scrobble(lastfm, pending)
                    continue

                buffer.append(chunk)
                self._flush_scrobble(lastfm, pending)
                if not self._is_audio_active(chunk):
                    if last_audio_at and datetime.utcnow() - last_audio_at > timedelta(
                        seconds=self.silence_tolerance_seconds
                    ):
                        audio_active = False
                    continue

                last_audio_at = chunk.recorded_at
                if not audio_active:
                    LOGGER.info("Audio detected above threshold (rms=%.4f)", chunk.rms)
                    audio_active = True

                if chunk.recorded_at - last_recognition_at < timedelta(
                    seconds=self.recognition_cooldown_seconds
                ):
                    continue

                clip = buffer.recent_clip()
                if clip is None:
                    continue

                recognition = recognizer.recognize_samples(clip, settings.audio_sample_rate)
                last_recognition_at = datetime.utcnow()
                if recognition is None or not recognition.title or not recognition.artist:
                    continue

                LOGGER.info(
                    "Shazam candidate: %s - %s (offset=%ss)",
                    recognition.artist,
                    recognition.title,
                    recognition.offset_seconds,
                )
                validated = discogs.validate(recognition)
                if validated is None:
                    continue

                started_at = recognition.recognized_at - timedelta(seconds=recognition.offset_seconds)
                if pending and same_track(pending.track, validated):
                    LOGGER.info("Ignoring duplicate recognition for %s - %s", validated.artist, validated.title)
                    continue

                pending = build_pending_scrobble(validated, started_at)
                if not pending.now_playing_sent:
                    lastfm.update_now_playing(validated)
                    pending.now_playing_sent = True
                self._flush_scrobble(lastfm, pending)

    def _flush_scrobble(self, lastfm: LastFMClient, pending: PendingScrobble | None) -> None:
        if not pending or pending.scrobbled:
            return
        if datetime.utcnow() < pending.scrobble_at:
            return
        lastfm.scrobble(pending.track, pending.started_at)
        pending.scrobbled = True

    def _is_audio_active(self, chunk: AudioChunk) -> bool:
        return chunk.rms >= self.silence_threshold


def main() -> None:
    CoreService().run()


if __name__ == "__main__":
    main()
