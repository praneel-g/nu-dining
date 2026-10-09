"""Collect Northeastern dining locations, payment options, and hours as JSON."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from datetime import date, datetime
from zoneinfo import ZoneInfo
from pathlib import Path

from .models import DATA_FILE, PAYMENTS, WEEKDAYS, DiningData, Location, Payment
from .net import FetchError
from .sources import dine_on_campus, husky_campus, husky_vendors
from .sources.geocode import geocode, in_boston


def add_coordinates(locations: list[Location]) -> None:
    """Geocode every location whose coordinates are missing or implausible."""
    needed = [
        loc
        for loc in locations
        if loc["address"] and not in_boston(loc["latitude"], loc["longitude"])
    ]
    print(f"Geocoding {len(needed)} addresses…")
    found = geocode(sorted({loc["address"] for loc in needed if loc["address"]}))
    for loc in needed:
        loc["latitude"], loc["longitude"] = found.get(loc["address"] or "", (None, None))


def boston_today() -> date:
    """Today's date in Boston; scheduled runs happen on UTC servers."""
    return datetime.now(ZoneInfo("America/New_York")).date()


def load_previous(path: Path) -> list[Location]:
    """Locations from the last scrape, if there was one."""
    try:
        previous: DiningData = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    return previous["restaurants"] + previous["markets"]


def keep_previous_data(locations: list[Location], previous: list[Location], day: date) -> None:
    """Fill hours and coordinates that this run couldn't get from the last run.

    Sources such as Overpass and vendor sites fail intermittently; a
    location shouldn't lose its hours just because one run hit an outage.
    """
    by_key = {(loc["source"], loc["name"]): loc for loc in previous}
    for location in locations:
        old = by_key.get((location["source"], location["name"]))
        if old is None:
            continue
        if location["weekly_hours"] is None and old["weekly_hours"]:
            location["weekly_hours"] = old["weekly_hours"]
            location["hours"] = old["weekly_hours"].get(WEEKDAYS[day.weekday()])
            location["hours_text"] = old["hours_text"]
            source = old["hours_source"] or "unknown source"
            location["hours_source"] = (
                source if "previous scrape" in source else f"{source}, kept from a previous scrape"
            )
        if location["latitude"] is None and old["latitude"] is not None:
            location["latitude"], location["longitude"] = old["latitude"], old["longitude"]


def scrape_source(
    source: str, scrape: Callable[[], list[Location]], previous: list[Location], day: date
) -> list[Location]:
    """Run one source's scraper, falling back to its previous results if its site is down."""
    try:
        return scrape()
    except FetchError as error:
        kept = [location for location in previous if location["source"] == source]
        print(f"  Warning: {error}\n  Keeping {len(kept)} locations from the previous scrape.")
        for location in kept:
            weekly = location["weekly_hours"]
            location["hours"] = weekly.get(WEEKDAYS[day.weekday()]) if weekly else None
        return kept


def build_dataset(day: date, use_browser: bool, previous: list[Location]) -> DiningData:
    """Scrape every source and group the locations for the website."""
    print("Fetching on-campus locations…")
    locations = scrape_source(
        dine_on_campus.SOURCE_NAME, lambda: dine_on_campus.scrape_on_campus(day), previous, day
    )
    print("Fetching off-campus vendors and their hours…")
    locations += scrape_source(
        husky_vendors.SOURCE_NAME,
        lambda: husky_vendors.scrape_off_campus(day, use_browser),
        previous,
        day,
    )
    print("Checking the Husky Card campus list for payments and anything missing…")
    known = list(locations)
    locations += scrape_source(
        husky_campus.SOURCE_NAME,
        lambda: husky_campus.scrape_campus_extras(known, day, use_browser),
        previous,
        day,
    )
    locations.sort(key=lambda location: location["name"].casefold())
    add_coordinates(locations)
    # Only after geocoding, so a stale pin never overrides a fresh lookup.
    keep_previous_data(locations, previous, day)

    def names_accepting(payment: Payment) -> list[str]:
        return [loc["name"] for loc in locations if payment in loc["payment"]]

    def in_category(category: str) -> list[Location]:
        return [loc for loc in locations if loc["category"] == category]

    return {
        "retrieved_on": boston_today().isoformat(),
        "hours_for_date": day.isoformat(),
        "sources": [dine_on_campus.PAGE_URL, husky_vendors.PAGE_URL, husky_campus.PAGE_URL],
        "restaurants": in_category("restaurant"),
        "markets": in_category("market"),
        "by_payment": {payment: names_accepting(payment) for payment in PAYMENTS},
    }


def main() -> None:
    """Parse arguments, scrape, and write the JSON file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DATA_FILE,
        help="JSON file to write (default: site/data/dining_locations.json)",
    )
    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        default=boston_today(),
        help="Date whose hours fill each location's 'hours' field (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Skip the Selenium/Firefox fallback for off-campus vendor hours",
    )
    args = parser.parse_args()

    data = build_dataset(args.date, not args.no_browser, load_previous(args.output))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    total = len(data["restaurants"]) + len(data["markets"])
    print(f"Wrote {total} locations to {args.output}")


if __name__ == "__main__":
    main()
