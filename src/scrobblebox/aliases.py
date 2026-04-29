from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from scrobblebox.config import settings


def _normalize_alias_entry(value: object) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        cleaned: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                cleaned.append(item.strip())
        return cleaned
    return []


@lru_cache(maxsize=1)
def artist_alias_map() -> dict[str, list[str]]:
    path = settings.artist_alias_file
    if not path:
        return {}

    alias_path = Path(path)
    if not alias_path.exists():
        return {}

    payload = json.loads(alias_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {}

    aliases: dict[str, list[str]] = {}
    for key, value in payload.items():
        if not isinstance(key, str) or not key.strip():
            continue
        variants = [key.strip(), *_normalize_alias_entry(value)]
        unique: list[str] = []
        seen: set[str] = set()
        for variant in variants:
            folded = variant.casefold()
            if folded in seen:
                continue
            seen.add(folded)
            unique.append(variant)
        aliases[key.strip().casefold()] = unique
    return aliases


def artist_variants(value: str) -> list[str]:
    cleaned = value.strip()
    if not cleaned:
        return []
    aliases = artist_alias_map().get(cleaned.casefold(), [])
    variants = [cleaned, *aliases]
    unique: list[str] = []
    seen: set[str] = set()
    for variant in variants:
        folded = variant.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        unique.append(variant)
    return unique
