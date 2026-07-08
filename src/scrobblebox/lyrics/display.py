from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from scrobblebox.aliases import artist_variants
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


def artist_query_variants(value: str) -> list[str]:
    candidates: list[str] = []
    for variant in artist_variants(value):
        candidates.extend(query_variants(variant))
    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        folded = candidate.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        unique.append(candidate)
    return unique


DEFAULT_TRACK_SECONDS = 210
LYRIC_END_GRACE_SECONDS = 8
MIN_TRACK_SECONDS = 90
LYRIC_PLACEHOLDER = "\u266a"
TIMING_OUTLIER_SECONDS = 8.0
RECOGNITION_PIN_SECONDS = 30.0


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
        artists = artist_query_variants(str(state.get("lyric_artist") or state.get("artist") or ""))
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

                    scored: list[tuple[float, dict[str, Any], LyricsDocument]] = []
                    for candidate in results:
                        document = self._document_from_result(candidate)
                        scored.append((self._candidate_score(state, candidate, document), candidate, document))
                    scored.sort(key=lambda item: item[0], reverse=True)
                    _, best, document = scored[0]
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
                lines=[],
                instrumental=bool(result.get("instrumental", False)),
            )
        return LyricsDocument(lines=[], instrumental=bool(result.get("instrumental", False)))

    def _candidate_score(self, state: dict[str, Any], result: dict[str, Any], document: LyricsDocument) -> float:
        score = 0.0
        if result.get("syncedLyrics"):
            score += 100.0
        elif result.get("plainLyrics"):
            score += 10.0

        title = str(state.get("lyric_title") or state.get("title") or "").strip().casefold()
        artist = str(state.get("lyric_artist") or state.get("artist") or "").strip().casefold()
        album = str(state.get("lyric_album") or state.get("album") or "").strip().casefold()
        if str(result.get("trackName") or "").strip().casefold() == title:
            score += 20.0
        if str(result.get("artistName") or "").strip().casefold() == artist:
            score += 20.0
        if album and str(result.get("albumName") or "").strip().casefold() == album:
            score += 15.0

        explicit_duration = state.get("duration_seconds")
        candidate_duration = result.get("duration")
        try:
            explicit_duration = float(explicit_duration) if explicit_duration else None
        except (TypeError, ValueError):
            explicit_duration = None
        try:
            candidate_duration = float(candidate_duration) if candidate_duration else None
        except (TypeError, ValueError):
            candidate_duration = None
        if explicit_duration and candidate_duration:
            diff = abs(explicit_duration - candidate_duration)
            score += max(0.0, 20.0 - min(diff, 20.0))

        if document.lines:
            last_ts = float(document.lines[-1].time_seconds)
            if candidate_duration:
                diff = abs(candidate_duration - last_ts)
                score += max(0.0, 15.0 - min(diff, 15.0))
            if len(document.lines) >= 4:
                intervals = [round(document.lines[i + 1].time_seconds - document.lines[i].time_seconds, 2) for i in range(len(document.lines) - 1)]
                repeated = max(intervals.count(value) for value in set(intervals))
                if repeated >= max(6, len(intervals) // 2):
                    score -= 40.0
                if all(abs(value - 4.0) < 0.01 for value in intervals[: min(8, len(intervals))]):
                    score -= 60.0
        return score

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


class KoitoRepository:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "ScrobbleBox/0.1 (+https://github.com/ephun/scrobblebox)"})
        if settings.koito_token:
            self.session.headers.update({"Authorization": f"Bearer {settings.koito_token}"})
        self._cache: dict[tuple[str, str, str], CachedPlaycount] = {}

    def user_playcount(self, state: dict[str, Any]) -> int | None:
        if not settings.display_koito_stats or not settings.koito_url:
            return None

        artist = str(state.get("artist") or "").strip()
        title = str(state.get("title") or "").strip()
        album = str(state.get("album") or "").strip()
        if not artist or not title:
            return None

        key = (artist.casefold(), title.casefold(), album.casefold())
        cached = self._cache.get(key)
        now = utc_now()
        if cached and cached.expires_at > now:
            return cached.count

        if not settings.koito_token:
            self._cache[key] = CachedPlaycount(count=None, expires_at=now + timedelta(minutes=5))
            return None

        try:
            search_url = f"{settings.koito_url.rstrip('/')}/apis/web/v1/search"
            response = self.session.get(search_url, params={"q": title}, timeout=10)
            response.raise_for_status()
            payload = response.json()
            tracks = payload.get("tracks") or []

            best_track_id = None
            for track in tracks:
                track_title = str(track.get("title") or "").strip()
                if track_title.casefold() != title.casefold():
                    continue
                artists = track.get("artists") or []
                artist_names = [str(a.get("name") or "").strip().casefold() for a in artists]
                if artist.casefold() not in artist_names:
                    continue
                best_track_id = track.get("id")
                break

            if not best_track_id:
                self._cache[key] = CachedPlaycount(count=0, expires_at=now + timedelta(hours=1))
                return 0

            track_url = f"{settings.koito_url.rstrip('/')}/apis/web/v1/track"
            track_resp = self.session.get(track_url, params={"id": best_track_id}, timeout=10)
            track_resp.raise_for_status()
            track_payload = track_resp.json()
            count = int(track_payload.get("listen_count") or 0)
            self._cache[key] = CachedPlaycount(count=count, expires_at=now + timedelta(hours=6))
            return count
        except Exception:
            self._cache[key] = CachedPlaycount(count=None, expires_at=now + timedelta(minutes=5))
            return None


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


def robust_started_at(state: dict[str, Any]) -> datetime | None:
    """Estimate when the current track started from recognition timing samples.

    Uses the median to anchor, then averages only the samples within
    TIMING_OUTLIER_SECONDS of it. A single bad Shazam offset (common right at
    the start of a track, when the clip matches the wrong section) previously
    poisoned a plain mean and made the lyric clock lurch.
    """
    samples = timing_sample_datetimes(state)
    if not samples:
        return parse_iso_utc(state.get("started_at"))
    timestamps = sorted(item.timestamp() for item in samples)
    mid = len(timestamps) // 2
    if len(timestamps) % 2:
        median = timestamps[mid]
    else:
        median = (timestamps[mid - 1] + timestamps[mid]) / 2
    kept = [value for value in timestamps if abs(value - median) <= TIMING_OUTLIER_SECONDS]
    if not kept:
        kept = [median]
    return datetime.fromtimestamp(sum(kept) / len(kept), tz=timezone.utc)


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


def max_confirmed_offset_seconds(state: dict[str, Any]) -> float:
    values: list[float] = []
    for raw in list(state.get("offset_seconds_samples") or []):
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value >= 0:
            values.append(value)
    return max(values) if values else 0.0


def last_recognition_datetime(state: dict[str, Any]) -> datetime | None:
    """When the core last confirmed this track via Shazam+Discogs.

    Falls back to updated_at for states written by older cores. The pin must
    key off actual recognitions, not arbitrary state writes: the old code used
    updated_at, which the core refreshed constantly, so the display stayed
    pinned to a finished track and next-track inference never ran.
    """
    return parse_iso_utc(state.get("last_recognition_at")) or parse_iso_utc(state.get("updated_at"))


def infer_track(
    raw_state: dict[str, Any],
    repo: LyricRepository,
    initial_lyrics: LyricsDocument | None,
) -> tuple[dict[str, Any], LyricsDocument | None, int]:
    """Resolve which track is actually playing right now.

    While a recognition is fresh, trust the recognized track. Once it goes
    stale and the wall clock says the recognized track must have ended, walk
    forward through the release tracklist (same side only — a side flip needs
    a needle drop we cannot infer) and present the track the stylus should be
    on, so the display keeps up between recognitions.
    """
    state = dict(raw_state)
    started_at = robust_started_at(state)
    if not started_at:
        return state, initial_lyrics, 0

    confirmed_offset = max_confirmed_offset_seconds(state)
    current_duration = estimated_duration_seconds(state, initial_lyrics)
    if confirmed_offset > 0:
        current_duration = max(current_duration, int(confirmed_offset + LYRIC_END_GRACE_SECONDS))

    release_tracks = list(state.get("release_tracks") or [])
    position = state.get("position")
    if not release_tracks or not position:
        return state, initial_lyrics, current_duration

    if not state.get("audio_active"):
        return state, initial_lyrics, current_duration

    recognized_at = last_recognition_datetime(state)
    if recognized_at is not None and (utc_now() - recognized_at).total_seconds() <= RECOGNITION_PIN_SECONDS:
        return state, initial_lyrics, current_duration

    index = next(
        (i for i, item in enumerate(release_tracks) if item.get("position") == position),
        None,
    )
    if index is None:
        return state, initial_lyrics, current_duration

    side = state.get("side")
    elapsed = (utc_now() - started_at).total_seconds()
    track_started_at = started_at
    is_current = True

    while index < len(release_tracks):
        track = release_tracks[index]
        if not is_current and track.get("side") != side:
            break

        if is_current:
            track_state: dict[str, Any] = state
            track_lyrics = initial_lyrics
            track_duration = current_duration
        else:
            track_state = inferred_track_state(state, track, track_started_at)
            try:
                track_lyrics = repo.load(track_state)
            except Exception:
                track_lyrics = None
            track_duration = estimated_duration_seconds(track_state, track_lyrics)

        if elapsed <= track_duration:
            return track_state, track_lyrics, track_duration

        elapsed -= track_duration
        track_started_at = track_started_at + timedelta(seconds=track_duration)
        index += 1
        is_current = False

    return state, initial_lyrics, current_duration


def current_line_index(lines: list[LyricLine], elapsed_seconds: float) -> int:
    """Index of the last line whose timestamp has passed, or -1 before the first."""
    index = -1
    for i, line in enumerate(lines):
        if line.time_seconds <= elapsed_seconds:
            index = i
        else:
            break
    return index


def lyric_cards(lyrics: LyricsDocument | None, elapsed_seconds: float, has_track: bool) -> tuple[str, str, str]:
    """Previous / current / next lyric card text for the display."""
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

    index = current_line_index(display_lines, elapsed_seconds)
    if index < 0:
        next_text = display_lines[0].text or LYRIC_PLACEHOLDER
        return ("", LYRIC_PLACEHOLDER, next_text)

    prev_text = display_lines[index - 1].text if index > 0 else ""
    current_text = display_lines[index].text or LYRIC_PLACEHOLDER
    next_text = display_lines[index + 1].text if index + 1 < len(display_lines) else ""
    prev_text = prev_text or (LYRIC_PLACEHOLDER if index > 0 else "")
    next_text = next_text or (LYRIC_PLACEHOLDER if index + 1 < len(display_lines) else "")
    return (prev_text, current_text, next_text)


class ElapsedSmoother:
    """Keep the displayed clock steady while timing estimates shift underneath.

    The timing estimate moves whenever a new recognition sample lands. Rather
    than letting the lyric clock lurch on every poll (the start-of-track
    "jump around for a few seconds" bug), smooth the track-start estimate:

    - new track: adopt the estimate immediately
    - tiny changes (< deadband): ignore
    - moderate changes: slew a fraction of the gap per poll, so the display
      glides to the corrected time over ~a second
    - large changes: require several consecutive polls to agree before
      snapping, so one outlier estimate never causes a visible jump
    """

    deadband_seconds: float = 0.4
    snap_threshold_seconds: float = 6.0
    slew_fraction: float = 0.25
    snap_patience_polls: int = 6

    def __init__(self) -> None:
        self._track_key: str | None = None
        self._started_at: float | None = None
        self._divergent_polls: int = 0

    def smooth(self, track_key: str, started_at: datetime | None) -> datetime | None:
        if started_at is None:
            self._track_key = None
            self._started_at = None
            self._divergent_polls = 0
            return None

        target = started_at.timestamp()
        if self._track_key != track_key or self._started_at is None:
            self._track_key = track_key
            self._started_at = target
            self._divergent_polls = 0
            return started_at

        gap = target - self._started_at
        if abs(gap) <= self.deadband_seconds:
            self._divergent_polls = 0
        elif abs(gap) <= self.snap_threshold_seconds:
            self._started_at += gap * self.slew_fraction
            self._divergent_polls = 0
        else:
            self._divergent_polls += 1
            if self._divergent_polls >= self.snap_patience_polls:
                self._started_at = target
                self._divergent_polls = 0
        return datetime.fromtimestamp(self._started_at, tz=timezone.utc)


def track_display_key(state: dict[str, Any]) -> str:
    return f"{state.get('release_id')}:{state.get('position')}:{state.get('title')}"


def prefetch_next_track_lyrics(state: dict[str, Any], repo: LyricRepository) -> None:
    """Warm the lyric cache for the next track on this side."""
    release_tracks = list(state.get("release_tracks") or [])
    index = next(
        (i for i, item in enumerate(release_tracks) if item.get("position") == state.get("position")),
        None,
    )
    if index is None or index + 1 >= len(release_tracks):
        return
    next_track = release_tracks[index + 1]
    if next_track.get("side") != state.get("side"):
        return
    try:
        repo.load(inferred_track_state(state, next_track, utc_now()))
    except Exception:
        pass


def build_view_model(
    raw_state: dict[str, Any],
    repo: LyricRepository,
    lastfm: LastfmRepository | None = None,
    koito: KoitoRepository | None = None,
    smoother: ElapsedSmoother | None = None,
) -> dict[str, Any]:
    initial_lyrics = None
    if raw_state.get("title"):
        try:
            initial_lyrics = repo.load(raw_state)
        except Exception:
            initial_lyrics = None

    inferred, lyrics, display_duration = infer_track(raw_state, repo, initial_lyrics)

    started_at = robust_started_at(inferred)
    if smoother is not None:
        started_at = smoother.smooth(track_display_key(inferred), started_at)
    elapsed = max(0.0, (utc_now() - started_at).total_seconds()) if started_at else 0.0
    lyric_elapsed = elapsed - settings.lyric_offset_seconds

    prev_text, current_text, next_text = lyric_cards(lyrics, lyric_elapsed, bool(inferred.get("title")))

    if inferred.get("title"):
        prefetch_next_track_lyrics(inferred, repo)

    inferred["elapsed_seconds"] = elapsed
    inferred["display_duration_seconds"] = int(display_duration or 0)
    inferred["started_at"] = started_at.isoformat() if started_at else inferred.get("started_at")
    inferred["previous_lyric"] = prev_text
    inferred["current_lyric"] = current_text
    inferred["next_lyric"] = next_text
    inferred["lastfm_playcount"] = lastfm.user_playcount(inferred) if lastfm else inferred.get("lastfm_playcount")
    inferred["koito_playcount"] = koito.user_playcount(inferred) if koito else inferred.get("koito_playcount")
    inferred["display_koito_stats"] = settings.display_koito_stats
    inferred["lyric_index"] = (
        current_line_index(lyrics.lines, lyric_elapsed)
        if lyrics and lyrics.lines and inferred.get("title")
        else -1
    )
    return inferred
