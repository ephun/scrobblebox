from __future__ import annotations

from datetime import datetime, timedelta

from scrobblebox.core.models import PendingScrobble, RecognitionResult, Track


def scrobble_due_at(started_at: datetime, duration_seconds: int | None) -> datetime:
    """Follow Last.fm's common scrobble threshold: 50% or 4 minutes, min 30s."""
    if duration_seconds is None or duration_seconds <= 0:
        return started_at + timedelta(seconds=30)
    threshold = max(30, min(240, duration_seconds / 2))
    return started_at + timedelta(seconds=threshold)


def same_track(left: Track, right: Track) -> bool:
    return (
        left.title.casefold() == right.title.casefold()
        and left.artist.casefold() == right.artist.casefold()
        and (left.album or "").casefold() == (right.album or "").casefold()
    )


def build_pending_scrobble(
    track: Track,
    started_at: datetime,
    recognition: RecognitionResult | None = None,
) -> PendingScrobble:
    timing_samples = [started_at]
    offset_samples: list[int] = []
    if recognition is not None:
        timing_samples = [recognition.recognized_at - timedelta(seconds=recognition.offset_seconds)]
        offset_samples = [recognition.offset_seconds]
    return PendingScrobble(
        track=track,
        started_at=started_at,
        scrobble_at=scrobble_due_at(started_at, track.duration_seconds),
        timing_started_at_samples=timing_samples,
        offset_seconds_samples=offset_samples,
    )
