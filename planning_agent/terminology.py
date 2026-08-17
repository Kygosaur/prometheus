"""Editable domain terminology used by local retrieval.

Add or remove equivalent phrases in TERMINOLOGY_GROUPS. Keep phrases lowercase;
queries and indexed text are normalized automatically.
"""

from __future__ import annotations

import re


TERMINOLOGY_GROUPS: dict[str, tuple[str, ...]] = {
    "protective headgear": ("helmet", "protective headgear"),
    "vehicle": ("automobile", "vehicle"),
    "personal protective equipment": ("ppe", "personal protective equipment"),
}


def expand_terminology(text: str) -> str:
    lowered = text.casefold()
    additions: list[str] = []
    for canonical, phrases in TERMINOLOGY_GROUPS.items():
        if any(re.search(rf"\b{re.escape(phrase)}\b", lowered) for phrase in phrases):
            additions.extend((canonical, *phrases))
    return f"{text} {' '.join(dict.fromkeys(additions))}" if additions else text

