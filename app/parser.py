from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any

from .geodata import find_locations

CLEAR_PATTERNS = (
    "відбій", "отбой", "не фіксується", "не фиксируется", "не відстежується",
    "не отслеживается", "не спостерігається", "не наблюдается", "впав", "впала",
    "упал", "упала", "збили", "сбили", "приземлили",
)

THREAT_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("FPV", ("fpv", "фпв")),
    ("Молнія", ("молнія", "молния", "molniya")),
    ("Shahed", ("shahed", "шахед", "герань")),
    ("КАБ", ("каб", "керована авіабомба", "упаб")),
    ("Балістика", ("баліст", "баллист")),
    ("РСЗВ", ("рсзв", "рсзо")),
    ("Ракета", ("ракет", "калібр", "калибр", "іскандер", "искандер", "кинджал", "кінджал")),
    ("БПЛА", ("бпла", "бплa", "дрон", "безпілот", "беспилот", "розвід", "развед")),
    ("Авіація", ("авіаці", "авиац", "літак", "самолет", "су-34", "су-35", "міг-31", "миг-31")),
]

DIRECTION_CUES = (
    "курс на", "курсом на", "у напрямку", "в напрямку", "в направлении",
    "далі на", "далее на", "рухається на", "движется на", "на місто", "на город",
)

NOISE_PATTERNS = (
    "реклама", "ваканс", "підписуй", "подписывай", "monobank", "приватбанк",
    "підтримати", "поддержать", "розіграш", "розыгрыш",
)


def classify(text: str) -> str | None:
    low = text.lower().replace("ё", "е")
    for kind, needles in THREAT_RULES:
        if any(n in low for n in needles):
            return kind
    return None


def is_clear(text: str) -> bool:
    low = text.lower().replace("ё", "е")
    return any(p in low for p in CLEAR_PATTERNS)


def looks_like_noise(text: str) -> bool:
    low = text.lower().replace("ё", "е")
    return any(p in low for p in NOISE_PATTERNS) and classify(text) is None


def _event_id(source_id: str, post_id: str, location: str, kind: str) -> str:
    raw = f"{source_id}|{post_id}|{location}|{kind}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:16]


def parse_message(
    *,
    source_id: str,
    source_name: str,
    post_id: str,
    text: str,
    published_at: datetime,
    url: str,
    weight: int = 1,
) -> dict[str, Any]:
    """Parse one public source message into a normalized event/action.

    Coordinates always come from public settlement/neighbourhood centroids in geodata.py.
    No target coordinate is inferred between settlements.
    """
    text = re.sub(r"\s+", " ", text).strip()
    if not text or looks_like_noise(text):
        return {"action": "ignore"}

    locations = find_locations(text)
    clear = is_clear(text)
    kind = classify(text)

    if clear:
        return {
            "action": "clear",
            "source_id": source_id,
            "locations": [x["label"] for x in locations],
            "published_at": published_at,
        }

    if kind is None:
        return {"action": "ignore"}

    # We only put a marker on the map when an explicit known public place is present.
    # Region-wide official warnings can use a coarse Kharkiv centroid in their adapter.
    if not locations:
        return {
            "action": "feed_only",
            "event": {
                "id": _event_id(source_id, post_id, "feed", kind),
                "kind": kind,
                "source_id": source_id,
                "source_name": source_name,
                "post_id": post_id,
                "text": text,
                "published_at": published_at.isoformat(),
                "url": url,
                "weight": weight,
                "mapped": False,
            },
        }

    target = locations[-1]
    origin = locations[0] if len(locations) > 1 else None
    low = text.lower().replace("ё", "е")
    has_direction = len(locations) > 1 or any(cue in low for cue in DIRECTION_CUES)

    event = {
        "id": _event_id(source_id, post_id, target["label"], kind),
        "kind": kind,
        "source_id": source_id,
        "source_name": source_name,
        "post_id": post_id,
        "text": text,
        "published_at": published_at.isoformat(),
        "url": url,
        "weight": weight,
        "mapped": True,
        "location": target["label"],
        "lat": target["lat"],
        "lon": target["lon"],
        "direction_to": target["label"] if has_direction else None,
        "direction_from": origin["label"] if origin and has_direction else None,
    }
    return {"action": "event", "event": event}
