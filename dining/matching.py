"""Fuzzy matching of business names and street addresses across sources."""

from __future__ import annotations

import html
import re


def street_key(address: str | None) -> tuple[int, str] | None:
    """Reduce an address to (house number, first street word) for matching.

    "Colonnade Hotel, 120 Huntington Ave" -> (120, "huntington").
    """
    if not address:
        return None
    match = re.search(r"\b(\d+)\s+([A-Za-z]+)", address)
    if not match:
        return None
    return int(match.group(1)), match.group(2).lower()


def same_street(first: str | None, second: str | None) -> bool:
    """Whether two addresses name the same street and roughly the same number.

    Storefronts often span several numbers (742 vs 744 Columbus Ave), so a
    small difference in house number still counts as a match.
    """
    first_key, second_key = street_key(first), street_key(second)
    if first_key is None or second_key is None:
        return False
    return first_key[1] == second_key[1] and abs(first_key[0] - second_key[0]) <= 10


def normalize_name(name: str) -> str:
    """Lowercase a name and drop punctuation: "Giovanni’s Market" -> "giovannis market"."""
    name = re.sub(r"['’`]", "", html.unescape(name).casefold())
    return " ".join(re.sub(r"[^a-z0-9]+", " ", name).split())


# Words too common to identify a business on their own.
GENERIC_WORDS = frozenset(
    {"the", "at", "and", "cafe", "market", "grocery", "pizza", "kitchen", "coffee", "coffees"}
)


def same_business(first: str, second: str) -> bool:
    """Whether two names likely refer to the same business.

    Either may contain the other ("Equator Coffees at Snell Library" vs
    "Equator Coffees"), or they share a leading distinctive word ("D'Angelo's"
    vs "D'Angelo Grilled Sandwiches", "Wollaston's Market" vs "Wollaston's Grocery").
    """
    first_name, second_name = normalize_name(first), normalize_name(second)
    if not first_name or not second_name:
        return False
    if first_name in second_name or second_name in first_name:
        return True

    def core(name: str) -> list[str]:
        return [word.rstrip("s") for word in name.split() if word not in GENERIC_WORDS]

    first_words, second_words = core(first_name), core(second_name)
    return bool(first_words and second_words and first_words[0] == second_words[0])


def with_building(address: str | None, building: str | None, name: str) -> str | None:
    """Prefix an address with its building unless the name or address already says it.

    ("360 Huntington Ave", "Curry Student Center", "Choolaah")
    -> "Curry Student Center, 360 Huntington Ave"
    """
    if not address or not building:
        return address
    key = normalize_name(building)
    if key in normalize_name(name) or key in normalize_name(address):
        return address
    return f"{building}, {address}"
