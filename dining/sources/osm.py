"""Opening hours and coordinates from OpenStreetMap, via the Overpass API."""

from __future__ import annotations

import re
from typing import NamedTuple
from urllib.parse import urlencode

from ..matching import normalize_name, same_street, street_key
from ..net import FetchError, fetch_json

# Public Overpass servers, tried in order; they are often overloaded.
OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
CAMPUS = (42.3398, -71.0892)
RADIUS_METERS = 3500


class OsmPlace(NamedTuple):
    """A named OpenStreetMap feature that has opening hours."""

    name: str
    address: str | None
    latitude: float
    longitude: float
    opening_hours: str


def fetch_osm_places(names: list[str]) -> list[OsmPlace]:
    """Features near campus whose names share a word with one of ``names``."""
    words = {
        max(normalize_name(name).split(), key=len) for name in names if normalize_name(name)
    }
    pattern = "|".join(sorted(re.escape(word) for word in words))
    query = (
        "[out:json][timeout:25];"
        f'nwr(around:{RADIUS_METERS},{CAMPUS[0]},{CAMPUS[1]})'
        f'["opening_hours"]["name"~"{pattern}",i];'
        "out tags center;"
    )
    # Overloaded servers fail intermittently, so go around the list twice.
    for url in OVERPASS_URLS * 2:
        try:
            payload = fetch_json(f"{url}?{urlencode({'data': query})}", referer=url)
        except (FetchError, ValueError):
            continue
        places = []
        for element in payload.get("elements", []):
            tags = element.get("tags", {})
            center = element.get("center", element)
            number, street = tags.get("addr:housenumber"), tags.get("addr:street")
            places.append(
                OsmPlace(
                    name=tags["name"],
                    address=f"{number} {street}" if number and street else None,
                    latitude=center["lat"],
                    longitude=center["lon"],
                    opening_hours=tags["opening_hours"],
                )
            )
        return places
    return []


def find_osm_place(places: list[OsmPlace], name: str, address: str) -> OsmPlace | None:
    """The feature for a vendor: names must overlap, and addresses must agree.

    "CVS" matches "CVS Pharmacy" at the same street address. A feature with
    no address is accepted only when it is the only one with that name.
    """
    wanted = normalize_name(name)

    def names_match(place: OsmPlace) -> bool:
        other = normalize_name(place.name)
        return bool(other) and (wanted in other or other in wanted)

    candidates = [place for place in places if names_match(place)]
    for place in candidates:
        if street_key(place.address) and same_street(place.address, address):
            return place
    unaddressed = [place for place in candidates if not street_key(place.address)]
    return unaddressed[0] if len(candidates) == 1 and unaddressed else None
