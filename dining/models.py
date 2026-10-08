"""Shared record types and constants for the dining data."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, TypedDict

DATA_FILE = Path(__file__).resolve().parent.parent / "site" / "data" / "dining_locations.json"


# Full weekday names indexed like ``date.weekday()`` (Monday is 0).
WEEKDAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


Category = Literal["restaurant", "market"]
Payment = Literal["meal_swipes", "dining_dollars"]
WeeklyHours = dict[str, list[str]]


class Location(TypedDict):
    """One dining location in the output JSON."""

    source: str
    name: str
    category: Category
    address: str | None
    latitude: float | None
    longitude: float | None
    payment: list[Payment]
    hours: list[str] | None
    weekly_hours: WeeklyHours | None
    hours_text: list[str] | None
    hours_source: str | None
    status: str | None
    url: str | None


class DiningData(TypedDict):
    """The JSON file written by ``python -m dining.scrape`` and read by the website."""

    retrieved_on: str
    hours_for_date: str
    sources: list[str]
    restaurants: list[Location]
    markets: list[Location]
    by_payment: dict[Payment, list[str]]
