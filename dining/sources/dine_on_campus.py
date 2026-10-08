"""On-campus dining locations and hours from the Dine On Campus API."""

from __future__ import annotations

import re
from datetime import date
from typing import Any
from urllib.parse import urlencode

from ..models import WEEKDAYS, Category, Location, Payment, WeeklyHours
from ..matching import with_building
from ..net import fetch_json

SOURCE_NAME = "Dine On Campus"
PAGE_URL = "https://dineoncampus.com/public/hours-of-operation"
SITE_ID = "5751fd2b90975b60e048929a"
API_ROOT = "https://apiv4.dineoncampus.com"

# Convenience stores; everything else on campus is a restaurant or café.
MARKET_PATTERN = re.compile(r"^the market\b|\bouttakes\b", re.IGNORECASE)


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


def fetch_places() -> dict[str, dict[str, Any]]:
    """Map each location id to its record from the locations API."""
    query = urlencode({"for_map": "true", "locale": "en"})
    payload = fetch_json(
        f"{API_ROOT}/sites/{SITE_ID}/locations-public?{query}",
        referer="https://dineoncampus.com/public/locations",
    )
    locations = [
        location
        for building in payload.get("buildings", [])
        for location in building.get("locations", [])
    ]
    locations += payload.get("standaloneLocations", [])
    return {location["id"]: location for location in locations}


def scrape_on_campus(day: date) -> list[Location]:
    """Return every on-campus location with its hours for the week of ``day``."""
    query = urlencode({"site_id": SITE_ID, "date": day.isoformat(), "locale": "en"})
    schedule = fetch_json(
        f"{API_ROOT}/locations/weekly_schedule?{query}", referer=PAGE_URL
    )
    places = fetch_places()

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

    records: list[Location] = []
    for location in schedule.get("theLocations", []):
        if location.get("is_building"):
            continue
        name = location.get("display_name") or location["name"]
        # The API numbers days from Sunday (0) to Saturday (6).
        weekly: WeeklyHours = {
            WEEKDAYS[(entry["day"] - 1) % 7]: day_hours(entry)
            for entry in location.get("week", [])
        }
        category: Category = "market" if MARKET_PATTERN.search(name) else "restaurant"
        place = places.get(location["id"], {})
        if not (place.get("address") or {}).get("street"):
            place = building_places.get(location.get("building_id"), place)
        address = place.get("address") or {}
        records.append(
            {
                "source": SOURCE_NAME,
                "name": name,
                "category": category,
                "address": with_building(
                    format_address(place),
                    building_names.get(location.get("building_id")) or address.get("metadata"),
                    name,
                ),
                "latitude": address.get("lat"),
                "longitude": address.get("lon"),
                "payment": accepted_payments(location),
                "hours": weekly.get(WEEKDAYS[day.weekday()]),
                "weekly_hours": weekly or None,
                "hours_text": None,
                "hours_source": SOURCE_NAME,
                "status": (location.get("status") or {}).get("label"),
                "url": f"https://dineoncampus.com/public/locations/{location['slug']}",
            }
        )
    return records
