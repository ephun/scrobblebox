from datetime import UTC, datetime, timedelta

import numpy as np

from scrobblebox.core.audio import AudioChunk, RollingAudioBuffer


def test_rolling_buffer_uses_audio_timeline_when_capture_clock_drifts() -> None:
    samplerate = 8
    buffer = RollingAudioBuffer(samplerate=samplerate, clip_seconds=2, max_seconds=4)
    started_at = datetime(2026, 1, 1, tzinfo=UTC)

    for index in range(4):
        chunk_started_at = started_at + timedelta(seconds=index / 2)
        chunk_ended_at = chunk_started_at + timedelta(seconds=0.5)
        buffer.append(
            AudioChunk(
                samples=np.full(4, index + 1, dtype=np.float32),
                started_at=chunk_started_at,
                ended_at=chunk_ended_at,
                recorded_at=chunk_ended_at,
                rms=0.1,
            )
        )

    clip = buffer.recent_clip()

    assert clip is not None
    assert len(clip.samples) == samplerate * 2
    assert clip.started_at == started_at


def test_rolling_buffer_evicts_old_chunks_on_audio_timeline() -> None:
    buffer = RollingAudioBuffer(samplerate=2, clip_seconds=1, max_seconds=2)
    started_at = datetime(2026, 1, 1, tzinfo=UTC)

    for index in range(4):
        chunk_started_at = started_at + timedelta(seconds=index)
        chunk_ended_at = chunk_started_at + timedelta(seconds=1)
        buffer.append(
            AudioChunk(
                samples=np.full(2, index + 1, dtype=np.float32),
                started_at=chunk_started_at,
                ended_at=chunk_ended_at,
                recorded_at=chunk_ended_at,
                rms=0.1,
            )
        )

    assert len(buffer._chunks) == 3
    assert buffer._chunks[0].started_at == started_at + timedelta(seconds=1)
