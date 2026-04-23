from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from scrobblebox.config import settings


@dataclass(slots=True)
class LyricLine:
    time_seconds: float
    text: str


@dataclass(slots=True)
class LyricsDocument:
    lines: list[LyricLine]
    instrumental: bool = False


def parse_iso_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def slugify(value: str) -> str:
    value = value.casefold().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


class LyricRepository:
    def __init__(self, root: Path = settings.lyrics_directory) -> None:
        self.root = root

    def load(self, state: dict[str, Any]) -> LyricsDocument | None:
        for path in self._candidate_paths(state):
            if path.exists():
                return self._read(path)
        return None

    def _candidate_paths(self, state: dict[str, Any]) -> list[Path]:
        title = slugify(state.get("title", ""))
        artist = slugify(state.get("artist", ""))
        album = slugify(state.get("album", ""))
        release_id = state.get("release_id")
        candidates: list[Path] = []
        if release_id:
            candidates.extend(
                [
                    self.root / f"{release_id}.lrc",
                    self.root / f"{release_id}.json",
                ]
            )
        if artist and title:
            candidates.extend(
                [
                    self.root / artist / album / f"{title}.lrc",
                    self.root / artist / album / f"{title}.json",
                    self.root / f"{artist}-{title}.lrc",
                    self.root / f"{artist}-{title}.json",
                ]
            )
        return candidates

    def _read(self, path: Path) -> LyricsDocument:
        if path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            return LyricsDocument(
                lines=[
                    LyricLine(float(item["time_seconds"]), str(item["text"]))
                    for item in payload.get("lines", [])
                ],
                instrumental=bool(payload.get("instrumental", False)),
            )

        lines: list[LyricLine] = []
        instrumental = False
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            if raw_line.strip().lower() == "[instrumental]":
                instrumental = True
                continue
            matches = list(re.finditer(r"\[(\d+):(\d+(?:\.\d+)?)\]", raw_line))
            if not matches:
                continue
            text = re.sub(r"\[[^\]]+\]", "", raw_line).strip()
            for match in matches:
                minutes = int(match.group(1))
                seconds = float(match.group(2))
                lines.append(LyricLine(minutes * 60 + seconds, text))
        lines.sort(key=lambda item: item.time_seconds)
        return LyricsDocument(lines=lines, instrumental=instrumental)


def infer_track(raw_state: dict[str, Any]) -> dict[str, Any]:
    state = dict(raw_state)
    started_at = parse_iso_utc(state.get("started_at"))
    duration = state.get("duration_seconds")
    if not started_at or not duration or duration <= 0:
        return state

    release_tracks = list(state.get("release_tracks") or [])
    position = state.get("position")
    side = state.get("side")
    if not release_tracks or not position:
        return state

    remaining = (utc_now() - started_at).total_seconds()
    current_index = next(
        (i for i, item in enumerate(release_tracks) if item.get("position") == position),
        None,
    )
    if current_index is None:
        return state

    while current_index < len(release_tracks):
        track = release_tracks[current_index]
        track_duration = track.get("duration_seconds")
        track_side = track.get("side")
        if current_index > 0 and track_side != side:
            break
        if not track_duration or track_duration <= 0:
            break
        if remaining <= track_duration:
            if current_index == 0:
                return state
            state["status"] = "inferred"
            state["title"] = track.get("title", state.get("title", ""))
            state["artist"] = track.get("artist") or state.get("artist", "")
            state["position"] = track.get("position")
            state["side"] = track_side
            state["duration_seconds"] = track_duration
            state["started_at"] = (utc_now() - timedelta(seconds=remaining)).isoformat()
            return state
        remaining -= track_duration
        current_index += 1

    return state


def lyric_cards(lyrics: LyricsDocument | None, elapsed_seconds: float, has_track: bool) -> tuple[str, str, str]:
    if not has_track:
        return ("Listening...", "Listening...", "Waiting for lyric sync.")
    if lyrics is None:
        return ("", "No lyrics available.", "")
    if lyrics.instrumental:
        return ("", "♪", "")
    if not lyrics.lines:
        return ("", "No lyrics available.", "")

    index = 0
    for i, line in enumerate(lyrics.lines):
        if line.time_seconds <= elapsed_seconds:
            index = i
        else:
            break
    prev_text = lyrics.lines[index - 1].text if index > 0 else ""
    current_text = lyrics.lines[index].text or "..."
    next_text = lyrics.lines[index + 1].text if index + 1 < len(lyrics.lines) else ""
    return (prev_text, current_text, next_text)


def build_view_model(raw_state: dict[str, Any], repo: LyricRepository) -> dict[str, Any]:
    inferred = infer_track(raw_state)
    started_at = parse_iso_utc(inferred.get("started_at"))
    elapsed = max(0, int((utc_now() - started_at).total_seconds())) if started_at else 0
    duration = inferred.get("duration_seconds") or 0

    # Never show backward motion: the browser increments locally between polls and the
    # server only moves the track start earlier, never later.
    lyrics = repo.load(inferred)
    prev_text, current_text, next_text = lyric_cards(lyrics, elapsed, bool(inferred.get("title")))

    inferred["elapsed_seconds"] = elapsed
    inferred["display_duration_seconds"] = duration if duration > 0 else 0
    inferred["previous_lyric"] = prev_text
    inferred["current_lyric"] = current_text
    inferred["next_lyric"] = next_text
    return inferred
