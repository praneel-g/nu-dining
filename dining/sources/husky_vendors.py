"""Off-campus Husky Card vendors and their opening hours."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from html.parser import HTMLParser
from typing import NamedTuple

from ..models import Category, Location
from ..net import fetch_husky_card_page
from .husky_map import fetch_map_points, find_point
from .osm import OsmPlace, fetch_osm_places, find_osm_place
from .vendor_sites import (
    Browser,
    VendorHours,
    hours_fields,
    parse_opening_hours,
    rendered_hours,
    static_hours,
)

SOURCE_NAME = "Husky Card off-campus vendors"
PAGE_URL = "https://huskycard.northeastern.edu/off-campus-vendors/"

# Pages with hours, for vendors whose Husky Card link is broken or has none.
HOURS_URLS = {
    "Wings Over Boston": "https://wingsover.com/location/ma-boston/",
    # The listed www address redirects slowly enough to time out.
    "Sprout": "https://sproutboston.com/",
    "Da Vinci Gelato and Waffle": "https://davincigelatowaffle.com/location-and-hours",
    # The live site blocks all automated clients; this 2023 copy is the only
    # source found, so its hours are labeled as possibly outdated.
    "Symphony Market": "https://web.archive.org/web/20231205223724id_/"
    "http://symphonymarket.net/index.html",
}

# The Husky Card page lists restaurants and stores together.
MARKETS = {"CVS", "Giovanni’s Market", "H Mart", "Star Market", "Symphony Market"}


class Vendor(NamedTuple):
    """One entry from the Husky Card vendor list."""

    name: str
    address: str
    url: str | None


class VendorListParser(HTMLParser):
    """Extract "Name, Address" list items from the Husky Card page."""

    def __init__(self) -> None:
        super().__init__()
        self.in_list_item = False
        self.text: list[str] = []
        self.url: str | None = None
        self.vendors: list[Vendor] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "li":
            self.in_list_item = True
            self.text = []
            self.url = None
        elif tag == "a" and self.in_list_item:
            self.url = dict(attrs).get("href")

    def handle_data(self, data: str) -> None:
        if self.in_list_item:
            self.text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "li" or not self.in_list_item:
            return
        self.in_list_item = False
        text = " ".join("".join(self.text).split())
        text = re.sub(r"\s+Temporarily Unavailable$", "", text)
        name, separator, address = text.partition(", ")
        if separator:
            self.vendors.append(Vendor(name, address, self.url))


def fetch_vendors() -> list[Vendor]:
    """The current vendor list from the Husky Card site."""
    parser = VendorListParser()
    parser.feed(fetch_husky_card_page("off-campus-vendors"))
    return parser.vendors


def find_all_hours(
    vendors: list[Vendor], osm_places: list[OsmPlace], use_browser: bool
) -> list[VendorHours | None]:
    """Look up each vendor's hours, cheapest source first.

    The vendor's own site wins (structured data, then a Firefox render), and
    OpenStreetMap fills in whatever is still missing.
    """

    urls = [HOURS_URLS.get(vendor.name, vendor.url) for vendor in vendors]

    def lookup(index: int) -> VendorHours | None:
        url = urls[index]
        return static_hours(url, vendors[index].address) if url else None

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lookup, range(len(vendors))))

    if use_browser:
        with Browser() as browser:
            for index, (vendor, url) in enumerate(zip(vendors, urls)):
                if results[index] is None and url:
                    print(f"  Rendering {vendor.name} in Firefox…")
                    results[index] = rendered_hours(browser, url, vendor.address)

    for index, vendor in enumerate(vendors):
        found = results[index]
        if found is None or found.weekly is None:
            place = find_osm_place(osm_places, vendor.name, vendor.address)
            weekly = parse_opening_hours(place.opening_hours) if place else {}
            if weekly:
                results[index] = VendorHours("OpenStreetMap", weekly=weekly)
    return results


def scrape_off_campus(day: date, use_browser: bool = True) -> list[Location]:
    """Return every Husky Card vendor with whatever hours could be found."""
    vendors = fetch_vendors()
    points = fetch_map_points()
    osm_places = fetch_osm_places([vendor.name for vendor in vendors])
    print(f"  {len(points)} Husky Card map pins, {len(osm_places)} OpenStreetMap matches")

    records: list[Location] = []
    for vendor, found in zip(vendors, find_all_hours(vendors, osm_places, use_browser)):
        category: Category = "market" if vendor.name in MARKETS else "restaurant"
        # Prefer the Husky Card office's own pin, then OpenStreetMap's; any
        # still missing are geocoded in scrape.py.
        pin = find_point(points, vendor.name, vendor.address) or find_osm_place(
            osm_places, vendor.name, vendor.address
        )
        records.append(
            {
                "source": SOURCE_NAME,
                "name": vendor.name,
                "category": category,
                "address": vendor.address,
                "latitude": pin.latitude if pin else None,
                "longitude": pin.longitude if pin else None,
                # Off-campus vendors take Dining Dollars (then Husky Dollars),
                # never meal swipes.
                "payment": ["dining_dollars"],
                **hours_fields(found, day),
                "status": None,
                "url": vendor.url,
            }
        )
    return records
