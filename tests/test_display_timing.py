from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scrobblebox.lyrics.display import (
    ElapsedSmoother,
    LyricsDocument,
    infer_track,
    robust_started_at,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class FakeRepo:
    """LyricRepository stand-in that never has lyrics."""

    def load(self, state):  # noqa: ANN001
        return None


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def playing_state(
    *,
    started_seconds_ago: float,
    recognized_seconds_ago: float,
    position: str = "A1",
    audio_active: bool = True,
) -> dict:
    now = utc_now()
    started = now - timedelta(seconds=started_seconds_ago)
    return {
        "status": "playing",
        "audio_active": audio_active,
        "title": "Track One",
        "artist": "Artist",
        "album": "Album",
        "release_id": 1,
        "side": "A",
        "position": position,
        "duration_seconds": 200,
        "started_at": iso(started),
        "updated_at": iso(now - timedelta(seconds=recognized_seconds_ago)),
        "last_recognition_at": iso(now - timedelta(seconds=recognized_seconds_ago)),
        "timing_started_at_samples": [iso(started)],
        "offset_seconds_samples": [30.0],
        "release_tracks": [
            {"title": "Track One", "artist": "Artist", "position": "A1", "side": "A", "duration_seconds": 200},
            {"title": "Track Two", "artist": "Artist", "position": "A2", "side": "A", "duration_seconds": 250},
            {"title": "Side Flip", "artist": "Artist", "position": "B1", "side": "B", "duration_seconds": 180},
        ],
    }


class TestRobustStartedAt:
    def test_outlier_sample_is_rejected(self) -> None:
        anchor = utc_now() - timedelta(seconds=100)
        state = {
            "timing_started_at_samples": [
                iso(anchor),
                iso(anchor + timedelta(seconds=1)),
                iso(anchor - timedelta(seconds=30)),  # bad Shazam offset
            ]
        }
        result = robust_started_at(state)
        assert result is not None
        # Mean of the two good samples; the 30s outlier must not drag it.
        assert abs((result - (anchor + timedelta(seconds=0.5))).total_seconds()) < 0.01

    def test_falls_back_to_started_at_without_samples(self) -> None:
        anchor = utc_now() - timedelta(seconds=42)
        state = {"started_at": iso(anchor), "timing_started_at_samples": []}
        result = robust_started_at(state)
        assert result is not None
        assert abs((result - anchor).total_seconds()) < 0.01


class TestElapsedSmoother:
    KEY = "1:A1:Track One"

    def test_adopts_first_estimate(self) -> None:
        smoother = ElapsedSmoother()
        anchor = utc_now()
        assert smoother.smooth(self.KEY, anchor) == anchor

    def test_ignores_deadband_jitter(self) -> None:
        smoother = ElapsedSmoother()
        anchor = utc_now()
        smoother.smooth(self.KEY, anchor)
        nudged = smoother.smooth(self.KEY, anchor + timedelta(seconds=0.2))
        assert abs((nudged - anchor).total_seconds()) < 0.01

    def test_slews_moderate_corrections(self) -> None:
        smoother = ElapsedSmoother()
        anchor = utc_now()
        smoother.smooth(self.KEY, anchor)
        target = anchor + timedelta(seconds=2)
        first = smoother.smooth(self.KEY, target)
        assert 0.3 < (first - anchor).total_seconds() < 0.7  # 25% of the gap
        for _ in range(30):
            latest = smoother.smooth(self.KEY, target)
        # Converges to within the deadband (it deliberately never chases jitter
        # smaller than that).
        assert abs((latest - target).total_seconds()) <= smoother.deadband_seconds + 0.01

    def test_one_outlier_never_jumps_the_clock(self) -> None:
        smoother = ElapsedSmoother()
        anchor = utc_now()
        smoother.smooth(self.KEY, anchor)
        wild = smoother.smooth(self.KEY, anchor + timedelta(seconds=25))
        assert abs((wild - anchor).total_seconds()) < 0.01

    def test_persistent_large_correction_snaps(self) -> None:
        smoother = ElapsedSmoother()
        anchor = utc_now()
        smoother.smooth(self.KEY, anchor)
        target = anchor + timedelta(seconds=25)
        for _ in range(smoother.snap_patience_polls):
            result = smoother.smooth(self.KEY, target)
        assert abs((result - target).total_seconds()) < 0.01

    def test_track_change_adopts_immediately(self) -> None:
        smoother = ElapsedSmoother()
        anchor = utc_now()
        smoother.smooth(self.KEY, anchor)
        new_start = anchor + timedelta(seconds=200)
        assert smoother.smooth("1:A2:Track Two", new_start) == new_start


class TestInferTrack:
    def test_fresh_recognition_pins_current_track(self) -> None:
        state = playing_state(started_seconds_ago=300, recognized_seconds_ago=5)
        inferred, _, _ = infer_track(state, FakeRepo(), None)
        assert inferred["position"] == "A1"
        assert inferred["status"] == "playing"

    def test_stale_recognition_advances_to_next_track(self) -> None:
        state = playing_state(started_seconds_ago=300, recognized_seconds_ago=120)
        inferred, _, duration = infer_track(state, FakeRepo(), None)
        assert inferred["position"] == "A2"
        assert inferred["status"] == "inferred"
        assert inferred["title"] == "Track Two"
        assert duration == 250
        started = datetime.fromisoformat(inferred["started_at"])
        elapsed_in_a2 = (utc_now() - started).total_seconds()
        assert 95 < elapsed_in_a2 < 105  # 300s in, A1 was 200s

    def test_does_not_walk_while_paused(self) -> None:
        state = playing_state(
            started_seconds_ago=300, recognized_seconds_ago=120, audio_active=False
        )
        inferred, _, _ = infer_track(state, FakeRepo(), None)
        assert inferred["position"] == "A1"

    def test_never_infers_across_side_boundary(self) -> None:
        state = playing_state(started_seconds_ago=500, recognized_seconds_ago=200)
        # 500s elapsed exhausts A1 (200s) + A2 (250s); B1 needs a side flip.
        inferred, _, _ = infer_track(state, FakeRepo(), None)
        assert inferred["position"] == "A1"
        assert inferred["status"] == "playing"

    def test_mid_side_track_keeps_recognized_state_while_playing(self) -> None:
        state = playing_state(
            started_seconds_ago=100, recognized_seconds_ago=60, position="A2"
        )
        state["title"] = "Track Two"
        state["duration_seconds"] = 250
        inferred, _, _ = infer_track(state, FakeRepo(), None)
        assert inferred["position"] == "A2"
        assert inferred["status"] == "playing"  # not rebuilt as "inferred"
