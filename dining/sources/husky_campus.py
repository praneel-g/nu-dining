"""Boston campus locations from the Husky Card "Dining Locations" page.

Most of these are already in the Dine On Campus data; this only adds the ones
that aren't, such as retail partners (Tatte, Saxbys, Fuel America).
"""

from __future__ import annotations

import re
from datetime import date
from html.parser import HTMLParser
from typing import NamedTuple

from ..matching import normalize_name, same_business, with_building
from ..models import Category, Location, Payment
from ..net import fetch_husky_card_page
from .husky_map import MapPoint, fetch_map_points, find_point
from .husky_vendors import Vendor, find_all_hours
from .osm import fetch_osm_places
from .vendor_sites import VendorHours, hours_fields

SOURCE_NAME = "Husky Card dining locations"
PAGE_URL = "https://huskycard.northeastern.edu/dining-halls/"


# Still listed on the Husky Card page but permanently closed.
CLOSED = {"Kigo Kitchen"}

# Branch pages with hours; the links on the Husky Card page go to chain homepages.
HOURS_URLS = {
    "Fuel America": "https://www.fuelamericacoffee.com/locations/fuel-america-northeastern/",
    "Saxbys": "https://www.saxbyscoffee.com/location/northeastern-university/",
    "Tatte Bakery and Cafe": "https://tattebakery.com/locations/ma/boston/369-huntington-avenue/",
    "Wollaston’s Market (Marino Center)":
        "https://www.wollastonsmarket.com/StoreLocator/Store/?L=10286",
    "Wollaston’s Market (West Village B)":
        "https://www.wollastonsmarket.com/StoreLocator/Store/?L=10287",
}


class CampusItem(NamedTuple):
    """One Boston campus entry on the page."""

    name: str
    building: str | None
    url: str | None
    residential: bool


class CampusListParser(HTMLParser):
    """Collect list items under each "Boston Campus" heading."""

    def __init__(self) -> None:
        super().__init__()
        # The heading being read, as (tag, text so far), if any.
        self.heading: tuple[str, list[str]] | None = None
        self.section = ""
        self.campus = ""
        # The list item being read, as (text so far, first link), if any.
        self.item: tuple[list[str], list[str]] | None = None
        self.items: list[CampusItem] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("h3", "h4"):
            self.heading = (tag, [])
        elif tag == "li":
            self.item = ([], [])
        elif tag == "a" and self.item is not None and not self.item[1]:
            self.item[1].append(dict(attrs).get("href") or "")

    def handle_data(self, data: str) -> None:
        if self.heading is not None:
            self.heading[1].append(data)
        elif self.item is not None:
            self.item[0].append(data)

    def handle_endtag(self, tag: str) -> None:
        if self.heading is not None and tag == self.heading[0]:
            text = " ".join("".join(self.heading[1]).split())
            if tag == "h3":
                self.section, self.campus = text, ""
            else:
                self.campus = text
            self.heading = None
        elif tag == "li" and self.item is not None:
            parts, links = self.item
            self.item = None
            if self.campus == "Boston Campus":
                self._add_item(" ".join("".join(parts).split()), links[0] if links else None)

    def _add_item(self, text: str, link: str | None) -> None:
        # "Outtakes at Stetson West (10 points/meal)+" -> name and building.
        text = re.sub(r"\((?:[^)]*(?:meal|swipe)[^)]*)\)", "", text).rstrip(" *+")
        match = re.match(r"^(.*?)\s*\(([^)]*)\)\s*$", text)
        name, building = (match.group(1).strip(), match.group(2)) if match else (text, None)
        # Links that go through email "safe links" aren't useful.
        url = link if link and "safelinks" not in link else None
        residential = self.section.startswith("Residential")
        # "Wollaston's Market (Marino Center, West Village B)" is two stores.
        buildings = [part.strip() for part in building.split(",")] if building else [None]
        for each in buildings:
            label = f"{name} ({each})" if len(buildings) > 1 else name
            self.items.append(CampusItem(label, each, url, residential))


def already_listed(name: str, existing: list[str]) -> bool:
    """Whether a name refers to one of the known locations."""
    return any(same_business(name, other) for other in existing)


def fetch_campus_items() -> list[CampusItem]:
    """Every Boston campus entry on the Husky Card dining locations page."""
    parser = CampusListParser()
    parser.feed(fetch_husky_card_page("dining-halls"))
    return parser.items


def _building_location(building: str | None, existing: list[Location]) -> Location | None:
    """A known location in the same building, to borrow its address from."""
    if not building:
        return None
    first = normalize_name(building.split(",")[0])
    for location in existing:
        text = normalize_name(f"{location['name']} {location['address'] or ''}")
        if first and f" {first} " in f" {text} " and location["address"]:
            return location
    return None


class Place(NamedTuple):
    """Where a campus location is."""

    address: str
    latitude: float | None
    longitude: float | None


def locate(item: CampusItem, existing: list[Location], points: list[MapPoint]) -> Place:
    """Address and coordinates: a known neighbor in the building, else the map pin."""
    neighbor = _building_location(item.building, existing)
    if neighbor:
        address = with_building(neighbor["address"], item.building, item.name) or ""
        return Place(address, neighbor["latitude"], neighbor["longitude"])
    pin = find_point(points, item.name.split(" (")[0], "")
    if pin and pin.address:
        # One pin can describe several stores: "Marino Center, 369 Huntington
        # Ave, and West Village, 460 Parker St." Its point is the first store.
        stores = re.split(r",? and ", pin.address)
        first_word = (item.building or "").split(" ")[0].lower()
        store = next((part for part in stores if first_word and first_word in part.lower()), None)
        address = with_building(store or pin.address, item.building, item.name) or ""
        if store is None or store == stores[0]:
            return Place(address, pin.latitude, pin.longitude)
        return Place(address, None, None)  # Geocoded later.
    return Place(item.building or "", None, None)


def to_record(item: CampusItem, place: Place, found: VendorHours | None, day: date) -> Location:
    """Build the output record for one campus location."""
    lowered = item.name.lower()
    category: Category = "market" if "market" in lowered or "grocery" in lowered else "restaurant"
    payment: list[Payment] = (
        ["meal_swipes", "dining_dollars"] if item.residential else ["dining_dollars"]
    )
    return {
        "source": SOURCE_NAME,
        "name": item.name,
        "category": category,
        "address": place.address or None,
        "latitude": place.latitude,
        "longitude": place.longitude,
        "payment": payment,
        **hours_fields(found, day),
        "status": None,
        "url": item.url,
    }


def scrape_campus_extras(
    existing: list[Location], day: date, use_browser: bool = True
) -> list[Location]:
    """Boston campus locations on the page that ``existing`` doesn't already cover."""
    names = [location["name"] for location in existing]
    items = [
        item
        for item in fetch_campus_items()
        if item.name not in CLOSED and not already_listed(item.name, names)
    ]
    if not items:
        return []
    print(f"  Adding {len(items)} campus locations: {', '.join(item.name for item in items)}")

    points = fetch_map_points()
    places = [locate(item, existing, points) for item in items]
    vendors = [
        Vendor(item.name, place.address, HOURS_URLS.get(item.name, item.url))
        for item, place in zip(items, places)
    ]
    osm_places = fetch_osm_places([item.name for item in items])
    all_hours = find_all_hours(vendors, osm_places, use_browser)
    return [
        to_record(item, place, found, day)
        for item, place, found in zip(items, places, all_hours)
    ]
