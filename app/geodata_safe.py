from __future__ import annotations

import re
from .geodata import LOCATIONS as BASE_LOCATIONS

# Extra public settlement centroids that are frequently used by monitoring channels.
EXTRA_LOCATIONS: dict[str, tuple[float, float, str]] = {
    "барвінкове": (48.9097, 37.0205, "Барвінкове"),
    "барвенково": (48.9097, 37.0205, "Барвінкове"),
    "близнюки": (48.8578, 36.5550, "Близнюки"),
    "ольшаны": (50.0575, 35.8850, "Вільшани"),
    "вільшани": (50.0575, 35.8850, "Вільшани"),
    "пересечное": (50.0231, 35.9788, "Пересічне"),
    "пересічне": (50.0231, 35.9788, "Пересічне"),
    "шевченково": (49.6941, 37.1730, "Шевченкове"),
    "шевченкове": (49.6941, 37.1730, "Шевченкове"),
    "шестаково": (50.0326, 36.7326, "Шестакове"),
    "шестакове": (50.0326, 36.7326, "Шестакове"),
    "довжик": (50.1737, 35.8345, "Довжик"),
    "черкасские тишки": (50.1420, 36.4300, "Черкаські Тишки"),
    "черкаські тишки": (50.1420, 36.4300, "Черкаські Тишки"),
    "ч. тишки": (50.1420, 36.4300, "Черкаські Тишки"),
}

LOCATIONS = dict(BASE_LOCATIONS)
LOCATIONS.update(EXTRA_LOCATIONS)

# These words occur frequently in normal news text and must never be matched by
# a plain substring search. "центр" caused false points from phrases such as
# "торговельного центру".
GENERIC_ALIASES = {"центр"}

CENTER_PATTERNS = (
    re.compile(r"(?iu)(?:у|в|на|до|из|із|с|з)?\s*центр(?:і|е)?\s+(?:харкова|харькова)"),
    re.compile(r"(?iu)центр\s+(?:харкова|харькова)"),
)


def _contains_alias(text: str, alias: str) -> bool:
    # Unicode-aware token boundaries. This prevents matching settlement aliases
    # inside unrelated words.
    pattern = rf"(?<![\w’']){re.escape(alias)}(?![\w’'])"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def find_locations(text: str) -> list[dict]:
    low = text.lower().replace("ё", "е")
    matches: list[dict] = []
    used: set[str] = set()

    # Handle city centre only when Kharkiv is explicitly mentioned.
    if any(p.search(low) for p in CENTER_PATTERNS):
        matches.append({"label": "Центр Харкова", "lat": 49.9930, "lon": 36.2320, "alias": "центр харкова"})
        used.add("Центр Харкова")

    for alias, (lat, lon, label) in sorted(LOCATIONS.items(), key=lambda x: len(x[0]), reverse=True):
        if alias in GENERIC_ALIASES or label in used:
            continue
        if _contains_alias(low, alias):
            matches.append({"label": label, "lat": lat, "lon": lon, "alias": alias})
            used.add(label)
    return matches
