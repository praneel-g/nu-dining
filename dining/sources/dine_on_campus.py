"""On-campus dining locations and hours from the Dine On Campus API."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlencode

from ..models import WEEKDAYS, Category, Location, Payment, WeeklyHours
from ..matching import with_building
from ..net import FetchError, fetch_json

SOURCE_NAME = "Dine On Campus"
# Each campus is its own Dine On Campus site: (site id, URL slug).
SITES = {
    "boston": ("5751fd2b90975b60e048929a", "public"),
    "oakland": ("634871aec625af01227663fe", "dining"),
}
API_ROOT = "https://apiv4.dineoncampus.com"

# Oakland's records all carry one point for the whole campus, so pins come
# from the building (or the location itself) instead, from OpenStreetMap:
# node 11201210269, way 1208931912, and way 23630929. Locations not listed
# here have no known spot and stay off the map.
OAKLAND_BUILDINGS = {
    "Tea Shop": (37.780854, -122.181600),
    "Adams Plaza": (37.780884, -122.181387),
    "Founders Commons": (37.781278, -122.179237),
}

# Convenience stores; everything else on campus is a restaurant or café.
MARKET_PATTERN = re.compile(r"^the market\b|\bouttakes\b", re.IGNORECASE)


def page_url(campus: str = "boston") -> str:
    """The public hours page for a campus."""
    return f"https://dineoncampus.com/{SITES[campus][1]}/hours-of-operation"


PAGE_URL = page_url()


def format_range(hour: dict[str, Any]) -> str:
    """Format one opening period from the schedule API."""
    if hour.get("always_open"):
        return "Open 24 hours"
    return (
        f"{hour['start_hour']:02d}:{hour['start_minutes']:02d}-"
        f"{hour['end_hour']:02d}:{hour['end_minutes']:02d}"
    )


def day_hours(entry: dict[str, Any]) -> list[str]:
    """All opening periods for one day; an empty list means closed."""
    if entry.get("always_open"):
        return ["Open 24 hours"]
    return [format_range(hour) for hour in entry.get("hours", [])]


def format_address(location: dict[str, Any]) -> str | None:
    """Join the street, city, state, and ZIP of a location record."""
    address = location.get("address") or {}
    parts = [address.get(key) for key in ("street", "city", "state", "zipCode")]
    return ", ".join(str(part) for part in parts if part) or None


def accepted_payments(location: dict[str, Any]) -> list[Payment]:
    """Which meal-plan payments a schedule record says it takes."""
    payments: list[Payment] = []
    if location.get("pay_with_meal_swipe"):
        payments.append("meal_swipes")
    if location.get("pay_with_dining_dollars"):
        payments.append("dining_dollars")
    return payments


def fetch_places(campus: str) -> dict[str, dict[str, Any]]:
    """Map each location id to its record from the locations API."""
    site_id, slug = SITES[campus]
    query = urlencode({"for_map": "true", "locale": "en"})
    payload = fetch_json(
        f"{API_ROOT}/sites/{site_id}/locations-public?{query}",
        referer=f"https://dineoncampus.com/{slug}/locations",
    )
    locations = [
        location
        for building in payload.get("buildings", [])
        for location in building.get("locations", [])
    ]
    locations += payload.get("standaloneLocations", [])
    return {location["id"]: location for location in locations}


def weekly_hours(location: dict[str, Any]) -> WeeklyHours:
    """A schedule record's opening periods for each weekday."""
    # The API numbers days from Sunday (0) to Saturday (6).
    return {
        WEEKDAYS[(entry["day"] - 1) % 7]: day_hours(entry)
        for entry in location.get("week", [])
    }


def menu_days(weekly: WeeklyHours, day: date) -> list[date]:
    """Days to look for a menu on: the next open day, or the whole week if none.

    The API lists no menus on days a location is closed. A listing with no
    hours at all may still carry the menu of a duplicate that has them.
    """
    week = [day + timedelta(days=offset) for offset in range(7)]
    open_days = [candidate for candidate in week if weekly.get(WEEKDAYS[candidate.weekday()])]
    return open_days[:1] or week


def has_menu(location_id: str, day: date) -> bool:
    """Whether a location publishes a menu (dining halls and some counters do).

    The API lists no menus on days a location is closed, so ``day`` should be
    one it is open.
    """
    query = urlencode({"platform": 0, "date": day.isoformat()})
    try:
        payload = fetch_json(
            f"{API_ROOT}/locations/{location_id}/periods/?{query}",
            referer="https://dineoncampus.com/",
        )
    except FetchError:
        # A missing link is better than failing the whole campus.
        return False
    return bool(payload.get("periods"))


def scrape_on_campus(day: date, campus: str = "boston") -> list[Location]:
    """Return every location on ``campus`` with its hours for the week of ``day``."""
    site_id, slug = SITES[campus]
    query = urlencode({"site_id": site_id, "date": day.isoformat(), "locale": "en"})
    schedule = fetch_json(
        f"{API_ROOT}/locations/weekly_schedule?{query}", referer=page_url(campus)
    )
    places = fetch_places(campus)

    # Some locations have no address of their own; borrow one from another
    # location in the same building.
    building_places = {
        location.get("building_id"): places[location["id"]]
        for location in schedule.get("theLocations", [])
        if (places.get(location["id"], {}).get("address") or {}).get("street")
    }

    building_names = {
        location["id"]: location["name"]
        for location in schedule.get("theLocations", [])
        if location.get("is_building")
    }

    # Keyed by slug: a location listed twice may have its menu on either copy.
    menu_slugs = {
        location["slug"]
        for location in schedule.get("theLocations", [])
        if not location.get("is_building")
        and any(
            has_menu(location["id"], candidate)
            for candidate in menu_days(weekly_hours(location), day)
        )
    }

    records: list[Location] = []
    for location in schedule.get("theLocations", []):
        if location.get("is_building"):
            continue
        name = location.get("display_name") or location["name"]
        weekly = weekly_hours(location)
        category: Category = "market" if MARKET_PATTERN.search(name) else "restaurant"
        place = places.get(location["id"], {})
        if not (place.get("address") or {}).get("street"):
            place = building_places.get(location.get("building_id"), place)
        address = place.get("address") or {}
        building = building_names.get(location.get("building_id"))
        latitude, longitude = address.get("lat"), address.get("lon")
        if campus == "oakland":
            latitude, longitude = OAKLAND_BUILDINGS.get(building or name, (None, None))
        records.append(
            {
                "source": SOURCE_NAME,
                "name": name,
                "category": category,
                "address": with_building(
                    format_address(place),
                    building or address.get("metadata"),
                    name,
                ),
                "latitude": latitude,
                "longitude": longitude,
                "payment": accepted_payments(location),
                "hours": weekly.get(WEEKDAYS[day.weekday()]),
                "weekly_hours": weekly or None,
                "hours_text": None,
                "hours_source": SOURCE_NAME,
                "hours_checked_on": None,
                "status": (location.get("status") or {}).get("label"),
                "url": f"https://dineoncampus.com/{slug}/locations/{location['slug']}",
                # Without a date, the menu page opens on today's menu.
                "menu_url": (
                    f"https://dineoncampus.com/{slug}/whats-on-the-menu/{location['slug']}"
                    if location["slug"] in menu_slugs
                    else None
                ),
            }
        )
    return without_duplicates(records)


def without_duplicates(records: list[Location]) -> list[Location]:
    """Drop repeated listings of one location, keeping the one with the most hours.

    The API sometimes lists a location twice under the same slug: once with
    its real schedule and once as a stale copy that is closed all week.
    """
    def open_periods(record: Location) -> int:
        return sum(len(periods) for periods in (record["weekly_hours"] or {}).values())

    best: dict[str | None, Location] = {}
    for record in records:
        kept = best.get(record["url"])
        if kept is None or open_periods(record) > open_periods(kept):
            best[record["url"]] = record
    return list(best.values())
