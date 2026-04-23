from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

import requests
from rapidfuzz import fuzz

from scrobblebox.config import settings
from scrobblebox.core.models import RecognitionResult, Track


LOGGER = logging.getLogger(__name__)
DISCOGS_API = "https://api.discogs.com"


def normalize_text(value: str) -> str:
    value = value.casefold().strip()
    value = re.sub(r"\([^)]*\)", " ", value)
    value = re.sub(r"\[[^\]]*\]", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def parse_duration_seconds(value: str | None) -> int | None:
    if not value:
        return None
    parts = value.strip().split(":")
    if not all(part.isdigit() for part in parts):
        return None
    total = 0
    for part in parts:
        total = total * 60 + int(part)
    return total


def track_side(position: str | None) -> str | None:
    if not position:
        return None
    match = re.match(r"([A-Z]+)", position.strip().upper())
    return match.group(1) if match else None


@dataclass(slots=True)
class CollectionRelease:
    release_id: int
    title: str
    artists: list[str]


class DiscogsClient:
    """Minimal Discogs REST client focused on collection-backed validation."""

    def __init__(self) -> None:
        self.username = settings.discogs_username
        self.folder_id = settings.discogs_collection_folder_id
        self.token = settings.discogs_token
        self.match_threshold = settings.discogs_match_threshold
        self.candidate_limit = settings.discogs_candidate_limit
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Discogs token={self.token}",
                "User-Agent": "ScrobbleBox/0.1 (+https://github.com/ephun/scrobblebox)",
            }
        )
        self._collection: list[CollectionRelease] | None = None
        self._release_cache: dict[int, dict[str, Any]] = {}

    def enabled(self) -> bool:
        return bool(self.username and self.token)

    def validate(self, recognition: RecognitionResult) -> Track | None:
        """Validate a Shazam result against the user's Discogs collection."""
        if not self.enabled():
            LOGGER.info("Discogs credentials missing; skipping collection validation")
            return Track(
                title=recognition.title,
                artist=recognition.artist,
                album=recognition.album or "",
            )

        candidates = self._candidate_releases(recognition)
        for candidate in candidates:
            detail = self._release_detail(candidate.release_id)
            track = self._match_track(recognition, detail)
            if track is not None:
                return track

        LOGGER.info(
            "Discarded Shazam match after Discogs validation failed: %s - %s",
            recognition.artist,
            recognition.title,
        )
        return None

    def _candidate_releases(self, recognition: RecognitionResult) -> list[CollectionRelease]:
        collection = self._load_collection()
        scored: list[tuple[int, CollectionRelease]] = []
        recognition_artist = normalize_text(recognition.artist)
        recognition_album = normalize_text(recognition.album or "")

        for release in collection:
            artist_score = max(
                fuzz.token_set_ratio(recognition_artist, normalize_text(artist)) for artist in release.artists
            ) if release.artists else 0
            album_score = fuzz.token_set_ratio(recognition_album, normalize_text(release.title)) if recognition_album else 0
            scored.append((artist_score + album_score, release))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [release for _, release in scored[: self.candidate_limit]]

    def _match_track(self, recognition: RecognitionResult, release_detail: dict[str, Any]) -> Track | None:
        release_title = str(release_detail.get("title", ""))
        release_artists = [artist.get("name", "") for artist in release_detail.get("artists", [])]
        best_match: tuple[int, Track] | None = None

        for entry in release_detail.get("tracklist", []):
            if entry.get("type_") and entry["type_"] != "track":
                continue

            entry_title = str(entry.get("title", ""))
            entry_artists = [artist.get("name", "") for artist in entry.get("artists", [])] or release_artists
            title_score = fuzz.token_set_ratio(
                normalize_text(recognition.title),
                normalize_text(entry_title),
            )
            artist_score = max(
                fuzz.token_set_ratio(normalize_text(recognition.artist), normalize_text(artist))
                for artist in entry_artists
            ) if entry_artists else 0
            total = title_score + artist_score
            track = Track(
                title=entry_title,
                artist=", ".join(entry_artists) if entry_artists else recognition.artist,
                album=release_title,
                release_id=int(release_detail["id"]),
                artwork_url=self._artwork_url(release_detail),
                side=track_side(entry.get("position")),
                position=entry.get("position"),
                duration_seconds=parse_duration_seconds(entry.get("duration")),
            )
            if best_match is None or total > best_match[0]:
                best_match = (total, track)

        if best_match and best_match[0] >= self.match_threshold:
            LOGGER.info(
                "Validated against Discogs release %s with score %s",
                best_match[1].release_id,
                best_match[0],
            )
            return best_match[1]
        return None

    def _load_collection(self) -> list[CollectionRelease]:
        if self._collection is not None:
            return self._collection

        page = 1
        per_page = 100
        releases: list[CollectionRelease] = []
        while True:
            url = (
                f"{DISCOGS_API}/users/{self.username}/collection/folders/{self.folder_id}/releases"
                f"?page={page}&per_page={per_page}"
            )
            payload = self._get(url)
            for item in payload.get("releases", []):
                info = item.get("basic_information", {})
                releases.append(
                    CollectionRelease(
                        release_id=int(info["id"]),
                        title=str(info.get("title", "")),
                        artists=[artist.get("name", "") for artist in info.get("artists", [])],
                    )
                )
            pagination = payload.get("pagination", {})
            if page >= int(pagination.get("pages", 1)):
                break
            page += 1

        LOGGER.info("Loaded %s releases from Discogs collection", len(releases))
        self._collection = releases
        return releases

    def _release_detail(self, release_id: int) -> dict[str, Any]:
        cached = self._release_cache.get(release_id)
        if cached is not None:
            return cached
        detail = self._get(f"{DISCOGS_API}/releases/{release_id}")
        self._release_cache[release_id] = detail
        return detail

    def _get(self, url: str) -> dict[str, Any]:
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _artwork_url(release_detail: dict[str, Any]) -> str | None:
        images = release_detail.get("images", [])
        if not images:
            return None
        primary = next((image for image in images if image.get("type") == "primary"), images[0])
        return primary.get("uri150") or primary.get("uri")
