from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from scrobblebox.config import settings


@dataclass(slots=True)
class LyricLine:
    time_seconds: float
    text: str


@dataclass(slots=True)
class LyricsDocument:
    lines: list[LyricLine]
    instrumental: bool = False


@dataclass(slots=True)
class CachedPlaycount:
    count: int | None
    expires_at: datetime


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


def ascii_fold(value: str) -> str:
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").strip()


def query_variants(value: str) -> list[str]:
    candidates = [value.strip()]
    ascii_value = ascii_fold(value)
    if ascii_value and ascii_value not in candidates:
        candidates.append(ascii_value)
    no_parens = re.sub(r"\([^)]*\)", " ", value).strip()
    if no_parens and no_parens not in candidates:
        candidates.append(no_parens)
    ascii_no_parens = ascii_fold(no_parens)
    if ascii_no_parens and ascii_no_parens not in candidates:
        candidates.append(ascii_no_parens)
    return [candidate for candidate in candidates if candidate]


DEFAULT_TRACK_SECONDS = 210
LYRIC_END_GRACE_SECONDS = 8
MIN_TRACK_SECONDS = 90
LYRIC_PLACEHOLDER = "\u266a"


class LyricRepository:
    def __init__(self, root: Path = settings.lyrics_directory) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "ScrobbleBox/0.1 (+https://github.com/ephun/scrobblebox)"})

    def load(self, state: dict[str, Any]) -> LyricsDocument | None:
        candidates = self._candidate_paths(state)
        for path in candidates:
            if path.exists():
                return self._read(path)
        fetched = self._fetch_and_cache(state, candidates)
        if fetched is not None:
            return fetched
        return None

    def _candidate_paths(self, state: dict[str, Any]) -> list[Path]:
        title = slugify(state.get("title", ""))
        artist = slugify(state.get("artist", ""))
        album = slugify(state.get("album", ""))
        release_id = state.get("release_id")
        position = slugify(state.get("position", ""))
        candidates: list[Path] = []
        if release_id and position:
            candidates.extend(
                [
                    self.root / str(release_id) / f"{position}.lrc",
                    self.root / str(release_id) / f"{position}.json",
                    self.root / str(release_id) / f"{position}-{title}.lrc",
                    self.root / str(release_id) / f"{position}-{title}.json",
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

    def _fetch_and_cache(self, state: dict[str, Any], candidates: list[Path]) -> LyricsDocument | None:
        titles = query_variants(str(state.get("lyric_title") or state.get("title") or ""))
        artists = query_variants(str(state.get("lyric_artist") or state.get("artist") or ""))
        albums = query_variants(str(state.get("lyric_album") or state.get("album") or ""))
        if not titles or not artists:
            return None
        duration = state.get("duration_seconds")
        for title in titles:
            for artist in artists:
                for album in albums or [""]:
                    params = {
                        "track_name": title,
                        "artist_name": artist,
                    }
                    if album:
                        params["album_name"] = album
                    if duration:
                        params["duration"] = duration

                    response = self.session.get("https://lrclib.net/api/search", params=params, timeout=20)
                    response.raise_for_status()
                    results = response.json()
                    if not results:
                        continue

                    best = results[0]
                    document = self._document_from_result(best)
                    target = next((path for path in candidates if path.suffix.lower() == ".json"), None)
                    if target is not None:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        payload = {
                            "instrumental": bool(best.get("instrumental", False)),
                            "lines": [
                                {"time_seconds": line.time_seconds, "text": line.text}
                                for line in document.lines
                            ],
                        }
                        target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
                    return document
        return None

    def _document_from_result(self, result: dict[str, Any]) -> LyricsDocument:
        synced = result.get("syncedLyrics")
        if synced:
            return self._parse_lrc(str(synced), instrumental=bool(result.get("instrumental", False)))
        plain = result.get("plainLyrics")
        if plain:
            return LyricsDocument(
                lines=[
                    LyricLine(float(index * 4), line)
                    for index, line in enumerate(str(plain).splitlines())
                    if line.strip()
                ],
                instrumental=bool(result.get("instrumental", False)),
            )
        return LyricsDocument(lines=[], instrumental=bool(result.get("instrumental", False)))

    def _parse_lrc(self, text: str, *, instrumental: bool = False) -> LyricsDocument:
        lines: list[LyricLine] = []
        for raw_line in text.splitlines():
            matches = list(re.finditer(r"\[(\d+):(\d+(?:\.\d+)?)\]", raw_line))
            if not matches:
                continue
            content = re.sub(r"\[[^\]]+\]", "", raw_line).strip()
            for match in matches:
                minutes = int(match.group(1))
                seconds = float(match.group(2))
                lines.append(LyricLine(minutes * 60 + seconds, content))
        lines.sort(key=lambda item: item.time_seconds)
        return LyricsDocument(lines=lines, instrumental=instrumental)


class LastfmRepository:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "ScrobbleBox/0.1 (+https://github.com/ephun/scrobblebox)"})
        self._cache: dict[tuple[str, str], CachedPlaycount] = {}

    def user_playcount(self, state: dict[str, Any]) -> int | None:
        artist = str(state.get("artist") or "").strip()
        title = str(state.get("title") or "").strip()
        if not artist or not title or not settings.lastfm_api_key or not settings.lastfm_username:
            return None

        key = (artist.casefold(), title.casefold())
        cached = self._cache.get(key)
        now = utc_now()
        if cached and cached.expires_at > now:
            return cached.count

        params = {
            "method": "track.getInfo",
            "api_key": settings.lastfm_api_key,
            "artist": artist,
            "track": title,
            "username": settings.lastfm_username,
            "autocorrect": 1,
            "format": "json",
        }
        try:
            response = self.session.get("https://ws.audioscrobbler.com/2.0/", params=params, timeout=20)
            response.raise_for_status()
            payload = response.json()
            track = payload.get("track") or {}
            raw_count = track.get("userplaycount")
            count = int(raw_count) if raw_count is not None else 0
            self._cache[key] = CachedPlaycount(count=count, expires_at=now + timedelta(hours=6))
            return count
        except Exception:
            self._cache[key] = CachedPlaycount(count=None, expires_at=now + timedelta(minutes=5))
            return None

    def _fetch_and_cache(self, state: dict[str, Any], candidates: list[Path]) -> LyricsDocument | None:
        titles = query_variants(str(state.get("lyric_title") or state.get("title") or ""))
        artists = query_variants(str(state.get("lyric_artist") or state.get("artist") or ""))
        albums = query_variants(str(state.get("lyric_album") or state.get("album") or ""))
        if not titles or not artists:
            return None
        duration = state.get("duration_seconds")
        for title in titles:
            for artist in artists:
                for album in albums or [""]:
                    params = {
                        "track_name": title,
                        "artist_name": artist,
                    }
                    if album:
                        params["album_name"] = album
                    if duration:
                        params["duration"] = duration

                    response = self.session.get("https://lrclib.net/api/search", params=params, timeout=20)
                    response.raise_for_status()
                    results = response.json()
                    if not results:
                        continue

                    best = results[0]
                    document = self._document_from_result(best)
                    target = next((path for path in candidates if path.suffix.lower() == ".json"), None)
                    if target is not None:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        payload = {
                            "instrumental": bool(best.get("instrumental", False)),
                            "lines": [
                                {"time_seconds": line.time_seconds, "text": line.text}
                                for line in document.lines
                            ],
                        }
                        target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
                    return document
        return None

    def _document_from_result(self, result: dict[str, Any]) -> LyricsDocument:
        synced = result.get("syncedLyrics")
        if synced:
            return self._parse_lrc(str(synced), instrumental=bool(result.get("instrumental", False)))
        plain = result.get("plainLyrics")
        if plain:
            return LyricsDocument(
                lines=[LyricLine(float(index * 4), line) for index, line in enumerate(str(plain).splitlines()) if line.strip()],
                instrumental=bool(result.get("instrumental", False)),
            )
        return LyricsDocument(lines=[], instrumental=bool(result.get("instrumental", False)))

    def _parse_lrc(self, text: str, *, instrumental: bool = False) -> LyricsDocument:
        lines: list[LyricLine] = []
        for raw_line in text.splitlines():
            matches = list(re.finditer(r"\[(\d+):(\d+(?:\.\d+)?)\]", raw_line))
            if not matches:
                continue
            content = re.sub(r"\[[^\]]+\]", "", raw_line).strip()
            for match in matches:
                minutes = int(match.group(1))
                seconds = float(match.group(2))
                lines.append(LyricLine(minutes * 60 + seconds, content))
        lines.sort(key=lambda item: item.time_seconds)
        return LyricsDocument(lines=lines, instrumental=instrumental)


def estimated_duration_seconds(state: dict[str, Any], lyrics: LyricsDocument | None) -> int:
    explicit_duration = state.get("duration_seconds")
    if explicit_duration and explicit_duration > 0:
        return int(explicit_duration)
    if lyrics and lyrics.lines:
        lyric_end = max(line.time_seconds for line in lyrics.lines)
        return max(MIN_TRACK_SECONDS, int(lyric_end + LYRIC_END_GRACE_SECONDS))
    return DEFAULT_TRACK_SECONDS


def timing_sample_datetimes(state: dict[str, Any]) -> list[datetime]:
    samples: list[datetime] = []
    for raw in list(state.get("timing_started_at_samples") or []):
        parsed = parse_iso_utc(str(raw))
        if parsed is not None:
            samples.append(parsed)
    return samples


def averaged_started_at(state: dict[str, Any]) -> datetime | None:
    samples = timing_sample_datetimes(state)
    if not samples:
        return parse_iso_utc(state.get("started_at"))
    average_timestamp = sum(item.timestamp() for item in samples) / len(samples)
    return datetime.fromtimestamp(average_timestamp, tz=timezone.utc)


def inferred_track_state(base_state: dict[str, Any], track: dict[str, Any], started_at: datetime) -> dict[str, Any]:
    state = dict(base_state)
    state["status"] = "inferred"
    state["title"] = track.get("title", state.get("title", ""))
    state["artist"] = track.get("artist") or state.get("artist", "")
    state["lyric_title"] = state["title"]
    state["lyric_artist"] = state["artist"]
    state["lyric_album"] = state.get("lyric_album") or state.get("album", "")
    state["position"] = track.get("position")
    state["side"] = track.get("side")
    state["duration_seconds"] = track.get("duration_seconds")
    state["started_at"] = started_at.isoformat()
    state["timing_started_at_samples"] = []
    state["offset_seconds_samples"] = []
    state["lastfm_playcount"] = None
    return state


def infer_track(raw_state: dict[str, Any], repo: LyricRepository, initial_lyrics: LyricsDocument | None) -> tuple[dict[str, Any], LyricsDocument | None, int]:
    state = dict(raw_state)
    started_at = averaged_started_at(state)
    if not started_at:
        return state, initial_lyrics, 0

    release_tracks = list(state.get("release_tracks") or [])
    position = state.get("position")
    side = state.get("side")
    if not release_tracks or not position:
        duration = estimated_duration_seconds(state, initial_lyrics)
        return state, initial_lyrics, duration

    remaining = (utc_now() - started_at).total_seconds()
    current_index = next(
        (i for i, item in enumerate(release_tracks) if item.get("position") == position),
        None,
    )
    if current_index is None:
        duration = estimated_duration_seconds(state, initial_lyrics)
        return state, initial_lyrics, duration

    current_started_at = started_at
    current_lyrics = initial_lyrics

    while current_index < len(release_tracks):
        track = release_tracks[current_index]
        track_side = track.get("side")
        if current_index > 0 and track_side != side:
            break

        track_state = state if current_index == 0 else inferred_track_state(state, track, current_started_at)
        track_lyrics = current_lyrics if current_index == 0 else repo.load(track_state)
        track_duration = estimated_duration_seconds(track_state, track_lyrics)
        if remaining <= track_duration:
            if current_index == 0:
                return state, track_lyrics, track_duration
            inferred_started_at = utc_now() - timedelta(seconds=remaining)
            inferred_state = inferred_track_state(state, track, inferred_started_at)
            return inferred_state, track_lyrics, track_duration
        remaining -= track_duration
        current_index += 1
        current_started_at = current_started_at + timedelta(seconds=track_duration)

    duration = estimated_duration_seconds(state, initial_lyrics)
    return state, initial_lyrics, duration


def lyric_cards(lyrics: LyricsDocument | None, elapsed_seconds: float, has_track: bool) -> tuple[str, str, str]:
    if not has_track:
        return ("Listening...", "Listening...", "Waiting for lyric sync.")
    if lyrics is None:
        return ("", "No lyrics available.", "")
    if lyrics.instrumental:
        return ("", "♪", "")
    if not lyrics.lines:
        return ("", "No lyrics available.", "")

    index = -1
    for i, line in enumerate(lyrics.lines):
        if line.time_seconds <= elapsed_seconds:
            index = i
        else:
            break
    if index < 0:
        next_text = lyrics.lines[0].text or LYRIC_PLACEHOLDER
        return ("", LYRIC_PLACEHOLDER, next_text)
    prev_text = lyrics.lines[index - 1].text if index > 0 else ""
    current_text = lyrics.lines[index].text or LYRIC_PLACEHOLDER
    next_text = lyrics.lines[index + 1].text if index + 1 < len(lyrics.lines) else ""
    return (prev_text, current_text, next_text)


def stable_lyric_cards(lyrics: LyricsDocument | None, elapsed_seconds: float, has_track: bool) -> tuple[str, str, str]:
    if not has_track:
        return ("Listening...", "Listening...", "Waiting for lyric sync.")
    if lyrics is None:
        return ("", "No lyrics available.", "")
    if lyrics.instrumental:
        return (LYRIC_PLACEHOLDER, LYRIC_PLACEHOLDER, LYRIC_PLACEHOLDER)
    if not lyrics.lines:
        return ("", "No lyrics available.", "")

    display_lines = lyrics.lines
    if lyrics.lines[0].time_seconds > 0:
        display_lines = [LyricLine(0.0, LYRIC_PLACEHOLDER), *lyrics.lines]

    index = -1
    for i, line in enumerate(display_lines):
        if line.time_seconds <= elapsed_seconds:
            index = i
        else:
            break
    if index < 0:
        next_text = display_lines[0].text or LYRIC_PLACEHOLDER
        return ("", LYRIC_PLACEHOLDER, next_text)

    prev_text = display_lines[index - 1].text if index > 0 else ""
    current_text = display_lines[index].text or LYRIC_PLACEHOLDER
    next_text = display_lines[index + 1].text if index + 1 < len(display_lines) else ""
    prev_text = prev_text or (LYRIC_PLACEHOLDER if index > 0 else "")
    next_text = next_text or (LYRIC_PLACEHOLDER if index + 1 < len(display_lines) else "")
    return (prev_text, current_text, next_text)


def build_view_model(raw_state: dict[str, Any], repo: LyricRepository, lastfm: LastfmRepository | None = None) -> dict[str, Any]:
    initial_lyrics = repo.load(raw_state) if raw_state.get("title") else None
    inferred, lyrics, display_duration = infer_track(raw_state, repo, initial_lyrics)
    started_at = averaged_started_at(inferred)
    elapsed = max(0, int((utc_now() - started_at).total_seconds())) if started_at else 0

    # Never show backward motion: the browser increments locally between polls and the
    # server only moves the track start earlier, never later.
    prev_text, current_text, next_text = stable_lyric_cards(lyrics, elapsed, bool(inferred.get("title")))

    if inferred.get("title"):
        release_tracks = list(inferred.get("release_tracks") or [])
        current_index = next(
            (i for i, item in enumerate(release_tracks) if item.get("position") == inferred.get("position")),
            None,
        )
        if current_index is not None and current_index + 1 < len(release_tracks):
            next_track = release_tracks[current_index + 1]
            if next_track.get("side") == inferred.get("side"):
                repo.load(inferred_track_state(inferred, next_track, utc_now()))

    inferred["elapsed_seconds"] = elapsed
    inferred["display_duration_seconds"] = int(display_duration or 0)
    inferred["started_at"] = started_at.isoformat() if started_at else inferred.get("started_at")
    inferred["previous_lyric"] = prev_text
    inferred["current_lyric"] = current_text
    inferred["next_lyric"] = next_text
    inferred["lastfm_playcount"] = lastfm.user_playcount(inferred) if lastfm else inferred.get("lastfm_playcount")
    inferred["lyric_index"] = -1
    if lyrics and lyrics.lines and inferred.get("title"):
        lyric_index = -1
        for i, line in enumerate(lyrics.lines):
            if line.time_seconds <= elapsed:
                lyric_index = i
            else:
                break
        inferred["lyric_index"] = lyric_index
    return inferred
