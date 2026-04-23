from datetime import datetime, timedelta

from scrobblebox.core.models import Track
from scrobblebox.core.runtime import build_pending_scrobble, same_track


def test_same_track() -> None:
    left = Track(title="Song", artist="Artist", album="Album")
    right = Track(title="song", artist="artist", album="album")
    assert same_track(left, right)


def test_pending_scrobble_threshold_is_at_least_30_seconds() -> None:
    started_at = datetime.utcnow()
    track = Track(title="Song", artist="Artist", album="Album", duration_seconds=20)
    pending = build_pending_scrobble(track, started_at)
    assert pending.scrobble_at - started_at == timedelta(seconds=30)
