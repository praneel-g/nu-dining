"""Street-address geocoding through OpenStreetMap's Nominatim service."""

from __future__ import annotations

import re
import time
from urllib.parse import urlencode

from ..net import FetchError, fetch_json

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# Greater Boston (west, north, east, south), so "Beacon St" can't resolve to
# another town's Beacon St.
WEST, NORTH, EAST, SOUTH = -71.20, 42.40, -70.98, 42.28
VIEWBOX = f"{WEST},{NORTH},{EAST},{SOUTH}"
# Nominatim's usage policy allows at most one request per second.
REQUEST_INTERVAL = 1.1


def in_boston(latitude: float | None, longitude: float | None) -> bool:
    """Whether coordinates are present and inside the greater Boston box."""
    if latitude is None or longitude is None:
        return False
    return SOUTH <= latitude <= NORTH and WEST <= longitude <= EAST


def _search(query: str, house_number: str | None) -> tuple[float, float] | None:
    """Search Nominatim, accepting only a result with the same house number.

    Without that check a street-level guess ("Beacon St, Boston") would pass
    for a specific building.
    """
    params = urlencode(
        {
            "q": query,
            "format": "jsonv2",
            "limit": 1,
            "viewbox": VIEWBOX,
            "bounded": 1,
            "addressdetails": 1,
        }
    )
    try:
        found = fetch_json(f"{NOMINATIM_URL}?{params}", referer="https://www.openstreetmap.org/")
    except FetchError:
        return None
    if not found:
        return None
    numbers = re.findall(r"\d+", found[0].get("address", {}).get("house_number", ""))
    if house_number and house_number not in numbers:
        return None
    return float(found[0]["lat"]), float(found[0]["lon"])


def geocode(addresses: list[str]) -> dict[str, tuple[float, float]]:
    """Map each address that Nominatim can find to its (latitude, longitude).

    Boston is tried first, since "279 Massachusetts Ave" also exists in
    Cambridge; then the rest of the area (such as Brookline).
    """
    results: dict[str, tuple[float, float]] = {}
    first = True
    for address in addresses:
        # Drop building names: "Colonnade Hotel, 120 Huntington Ave" -> "120 Huntington Ave".
        match = re.search(r"(\d+)\s.*", address)
        street = match.group(0) if match else address
        if "Boston" in address:
            queries = [address]
        else:
            queries = [f"{street}, Boston", f"{street}, Massachusetts"]
        for query in queries:
            if not first:
                time.sleep(REQUEST_INTERVAL)
            first = False
            found = _search(query, match.group(1) if match else None)
            if found:
                results[address] = found
                break
    return results
