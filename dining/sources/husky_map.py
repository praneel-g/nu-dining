"""Vendor coordinates from the Husky Card office's ArcGIS StoryMap.

The off-campus vendors page links to this map; each place's title is
"Name - Address" and its pin is the vendor's location.
"""

from __future__ import annotations

import html
import re
from typing import Any, NamedTuple

from ..matching import normalize_name, same_business, same_street, street_key
from ..net import FetchError, fetch_json

STORY_ID = "7637f8741ae94892a0d902bd32b57e25"
STORY_URL = f"https://storymaps.arcgis.com/stories/{STORY_ID}"
DATA_URL = f"https://www.arcgis.com/sharing/rest/content/items/{STORY_ID}/data?f=json"


class MapPoint(NamedTuple):
    """One pin on the Husky Card map."""

    name: str
    address: str
    latitude: float
    longitude: float


def _node_text(nodes: dict[str, Any], node_id: str) -> str:
    text = nodes.get(node_id, {}).get("data", {}).get("text", "")
    return html.unescape(re.sub(r"<[^>]+>", "", str(text))).strip()


def fetch_map_points() -> list[MapPoint]:
    """All pins on the map; an empty list if the map can't be read."""
    try:
        story = fetch_json(DATA_URL, referer=STORY_URL)
    except FetchError:
        return []
    nodes: dict[str, Any] = story.get("nodes", {})
    points: list[MapPoint] = []
    for tour in (node for node in nodes.values() if node.get("type") == "tour"):
        geometries = nodes.get(tour["data"].get("map"), {}).get("data", {}).get("geometries", {})
        for place in tour["data"].get("places", []):
            geometry = geometries.get(place.get("featureId"), {}).get("nodes") or [{}]
            name, _, address = _node_text(nodes, place.get("title", "")).partition(" - ")
            if "lat" in geometry[0] and name:
                points.append(
                    MapPoint(name, address, geometry[0]["lat"], geometry[0]["long"])
                )
    return points


def find_point(points: list[MapPoint], name: str, address: str) -> MapPoint | None:
    """The pin for a vendor: an exact name, a similar name, or the same street address.

    A name match is rejected when both addresses name different streets, so
    the off-campus Subway on Mass Ave doesn't get the campus Subway's pin.
    """
    wanted = normalize_name(name)

    def consistent(point: MapPoint) -> bool:
        both_known = street_key(point.address) and street_key(address)
        return not both_known or same_street(point.address, address)

    for point in points:
        if normalize_name(point.name) == wanted and consistent(point):
            return point
    for point in points:
        if same_business(point.name, name) and consistent(point):
            return point
    for point in points:
        if same_street(point.address, address):
            return point
    return None
