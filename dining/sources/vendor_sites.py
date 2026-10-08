"""Find opening hours on an off-campus vendor's own website.

Two strategies, cheapest first:

1. schema.org JSON-LD (``openingHours`` / ``openingHoursSpecification``),
   which many restaurant sites and chain store locators embed for search
   engines. This is fetched without a browser.
2. A headless Firefox render via Selenium, for sites that block plain HTTP
   clients or build the page with JavaScript. The rendered page is checked
   for JSON-LD again, then scanned for lines that look like opening hours.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import date
from html import unescape
from types import TracebackType
from typing import Any, Iterator, TypedDict
from urllib.parse import urljoin, urlparse

from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By

from ..matching import same_street, street_key
from ..models import WEEKDAYS, WeeklyHours
from ..net import FetchError, fetch_html

DAY_CODES = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")
JSON_LD_PATTERN = re.compile(
    r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", re.DOTALL | re.IGNORECASE
)
OPENING_HOURS_PATTERN = re.compile(
    r"((?:Mo|Tu|We|Th|Fr|Sa|Su)(?:\s*[-,]\s*(?:Mo|Tu|We|Th|Fr|Sa|Su))*)"
    r"\s+(\d{1,2}:\d\d)\s*-\s*(\d{1,2}:\d\d)"
)

_TIME = r"\d{1,2}(?::\d\d)?\s*[ap]\.?\s?m\.?"
_LOOSE_TIME = r"\d{1,2}(?::\d\d)?(?:\s*[ap]\.?\s?m\.?)?"
TIME_RANGE_PATTERN = re.compile(
    rf"{_LOOSE_TIME}\s*(?:-|–|—|to)\s*{_TIME}", re.IGNORECASE
)
DAY_PATTERN = re.compile(
    r"\b(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\b|\bdaily\b|\bevery ?day\b",
    re.IGNORECASE,
)
# A line holding only days, such as "Sunday" or "Monday - Saturday:".
DAY_LABEL_PATTERN = re.compile(
    rf"^(?:{DAY_PATTERN.pattern})"
    rf"(?:\s*(?:-|–|to|through|&|and)\s*(?:{DAY_PATTERN.pattern}))?[\s:,–-]*$",
    re.IGNORECASE,
)
HOURS_HEADING_PATTERN = re.compile(r"^(?:store |opening |our )?hours\b", re.IGNORECASE)

# How many lines after an address or "Hours" heading to search for hours.
ANCHOR_WINDOW = 18
# Longest to wait for a JavaScript-built page to settle.
MAX_RENDER_SECONDS = 15
# More distinct hours lines than this usually means a multi-location page.
MAX_TEXT_LINES = 10


class HoursFields(TypedDict):
    """The hours-related fields of a ``Location``."""

    hours: list[str] | None
    weekly_hours: WeeklyHours | None
    hours_text: list[str] | None
    hours_source: str | None


@dataclass
class VendorHours:
    """Hours found for one vendor and where they came from."""

    source: str
    weekly: WeeklyHours | None = None
    text: list[str] | None = None


def hours_fields(found: VendorHours | None, day: date) -> HoursFields:
    """Location fields for hours that were found (or not), with ``day``'s hours."""
    weekly = found.weekly if found else None
    return {
        "hours": weekly[WEEKDAYS[day.weekday()]] if weekly else None,
        "weekly_hours": weekly,
        "hours_text": found.text if found else None,
        "hours_source": found.source if found else None,
    }


# --- schema.org JSON-LD -----------------------------------------------------


def _json_ld_blocks(html: str) -> Iterator[Any]:
    for block in JSON_LD_PATTERN.findall(html):
        try:
            yield json.loads(block, strict=False)
        except json.JSONDecodeError:
            continue


def _businesses(node: Any) -> Iterator[dict[str, Any]]:
    """Yield every JSON-LD object that declares opening hours."""
    if isinstance(node, dict):
        if "openingHours" in node or "openingHoursSpecification" in node:
            yield node
        for child in node.values():
            yield from _businesses(child)
    elif isinstance(node, list):
        for child in node:
            yield from _businesses(child)


def _node_address(node: dict[str, Any]) -> str | None:
    address = node.get("address")
    if isinstance(address, str):
        return address
    if isinstance(address, dict):
        street = address.get("streetAddress")
        return street if isinstance(street, str) else None
    return None


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value]


def _expand_day_codes(spec: str) -> list[str]:
    """Turn "Mo-We,Fr" into ["Monday", "Tuesday", "Wednesday", "Friday"]."""
    days: list[str] = []
    for part in re.split(r"\s*,\s*", spec):
        bounds = [DAY_CODES.index(code) for code in re.split(r"\s*-\s*", part)]
        index = bounds[0]
        while True:
            days.append(WEEKDAYS[index])
            if index == bounds[-1]:
                break
            index = (index + 1) % 7
    return days


def _weekly_from_node(node: dict[str, Any]) -> WeeklyHours:
    weekly: WeeklyHours = {}
    for spec in _as_list(node.get("openingHoursSpecification") or []):
        if not isinstance(spec, dict) or not spec.get("opens"):
            continue
        period = f"{spec['opens'][:5]}-{spec['closes'][:5]}"
        for day in _as_list(spec.get("dayOfWeek") or []):
            name = str(day).rsplit("/", 1)[-1]
            if name in WEEKDAYS:
                weekly.setdefault(name, []).append(period)

    opening_hours = " ".join(str(item) for item in _as_list(node.get("openingHours") or []))
    for day, periods in parse_opening_hours(opening_hours).items():
        for period in periods:
            if period not in weekly.get(day, []):
                weekly.setdefault(day, []).append(period)

    if not weekly:
        return {}
    # schema.org treats days that are not listed as closed.
    return {day: weekly.get(day, []) for day in WEEKDAYS}


def parse_opening_hours(text: str) -> WeeklyHours:
    """Parse schema.org/OpenStreetMap hours like "Mo-Fr 09:00-17:00; Sa 10:00-14:00".

    Days that are not mentioned are closed. Returns {} if nothing parses.
    """
    if text.strip() == "24/7":
        return {day: ["Open 24 hours"] for day in WEEKDAYS}
    weekly: WeeklyHours = {}
    for days, opens, closes in OPENING_HOURS_PATTERN.findall(text):
        for name in _expand_day_codes(days):
            weekly.setdefault(name, []).append(f"{opens.zfill(5)}-{closes.zfill(5)}")
    return {day: weekly.get(day, []) for day in WEEKDAYS} if weekly else {}


def hours_from_json_ld(html: str, address: str | None) -> WeeklyHours | None:
    """Weekly hours for the business at ``address`` declared in JSON-LD.

    Chains often describe several branches on one page, so a business that
    states an address must match the vendor's. One that states no address is
    assumed to be the vendor.
    """
    fallback: WeeklyHours | None = None
    for block in _json_ld_blocks(html):
        for node in _businesses(block):
            weekly = _weekly_from_node(node)
            if not weekly:
                continue
            node_address = _node_address(node)
            if node_address is None:
                fallback = fallback or weekly
            elif same_street(node_address, address):
                return weekly
    return fallback


# --- visible page text ------------------------------------------------------


def _is_hours_line(line: str) -> bool:
    lowered = line.lower()
    if "closes at" in lowered or "opens at" in lowered or len(line) > 100:
        return False
    return bool(TIME_RANGE_PATTERN.search(line)) or (
        bool(DAY_PATTERN.search(line)) and "closed" in lowered and len(line) < 40
    )


def _hours_entries(lines: list[str]) -> list[tuple[int, str]]:
    """Hours lines with their index, joining day labels that sit on their own line."""
    entries: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        if not _is_hours_line(line):
            continue
        previous = lines[index - 1] if index else ""
        if not DAY_PATTERN.search(line) and DAY_LABEL_PATTERN.match(previous):
            line = f"{previous.rstrip(' :')}: {line}"
        elif entries and entries[-1][0] == index - 1 and not DAY_PATTERN.search(line):
            # A continuation such as "4-9 PM" after "Tue-Sat: 11 AM-3 PM,".
            entries[-1] = (index, f"{entries[-1][1]} {line}")
            continue
        entries.append((index, line))
    return entries


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def hours_from_text(text: str, address: str | None) -> list[str] | None:
    """Best-effort opening-hours lines from a page's visible text."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    entries = _hours_entries(lines)
    if not entries:
        return None

    anchors = [i for i, line in enumerate(lines) if same_street(line, address)]
    anchors += [
        i for i, line in enumerate(lines) if len(line) < 40 and HOURS_HEADING_PATTERN.match(line)
    ]
    for anchor in anchors:
        # Stop at the next address so a list of branches yields only ours.
        end = anchor + ANCHOR_WINDOW
        for index in range(anchor + 1, min(end, len(lines))):
            if not _is_hours_line(lines[index]) and street_key(lines[index]):
                end = index
                break
        found = _unique([line for index, line in entries if anchor < index < end])
        if 0 < len(found) <= MAX_TEXT_LINES:
            return found

    found = _unique([line for _, line in entries])
    return found if len(found) <= MAX_TEXT_LINES else None


def _to_24_hour(hour: str, minute: str | None, meridiem: str) -> str:
    value = int(hour) % 12 + (12 if meridiem == "p" else 0)
    return f"{value:02d}:{minute or '00'}"


def _parse_periods(text: str) -> list[str] | None:
    """Convert "11 AM-3 PM, 4-9 PM" into ["11:00-15:00", "16:00-21:00"]."""
    if "closed" in text.lower():
        return []
    periods = []
    for match in TIME_RANGE_PATTERN.finditer(text):
        times = re.findall(r"(\d{1,2})(?::(\d\d))?\s*([ap])?", match.group(0), re.IGNORECASE)
        (start_h, start_m, start_p), (end_h, end_m, end_p) = times[0], times[-1]
        end_p = end_p.lower()
        start_p = start_p.lower() or end_p  # "4-9 PM" means 4 PM to 9 PM.
        periods.append(
            f"{_to_24_hour(start_h, start_m, start_p)}-{_to_24_hour(end_h, end_m, end_p)}"
        )
    return periods or None


def _parse_days(text: str) -> list[str]:
    """Convert "Tue-Sat" or "Open Daily" into full weekday names."""
    lowered = text.lower()
    if "daily" in lowered or "every" in lowered:
        return list(WEEKDAYS)
    prefixes = [day[:3].lower() for day in WEEKDAYS]
    days: list[str] = []
    day_word = r"(mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?"
    for start, end in re.findall(
        rf"{day_word}(?:\s*(?:-|–|to|through)\s*{day_word})?", lowered
    ):
        index, last = prefixes.index(start), prefixes.index(end or start)
        days.append(WEEKDAYS[index])
        while index != last:
            index = (index + 1) % 7
            days.append(WEEKDAYS[index])
    return days


def weekly_from_text(lines: list[str]) -> WeeklyHours | None:
    """Structured weekly hours, if every scraped line is "<days> <times>".

    A single line with times but no days ("7AM - 1AM" under "Hours of
    Operation") is taken to mean every day.
    """
    if len(lines) == 1 and not DAY_PATTERN.search(lines[0]):
        periods = _parse_periods(lines[0])
        return {day: list(periods) for day in WEEKDAYS} if periods else None
    weekly: WeeklyHours = {}
    for line in lines:
        split = re.search(r"\d|closed", line, re.IGNORECASE)
        if not split:
            return None
        days = _parse_days(line[: split.start()])
        periods = _parse_periods(line[split.start() :])
        if not days or periods is None:
            return None
        for day in days:
            weekly.setdefault(day, []).extend(periods)
    return {day: weekly.get(day, []) for day in WEEKDAYS} if weekly else None


# --- fetching ---------------------------------------------------------------


class Browser:
    """A lazily started headless Firefox, shut down on context exit."""

    def __init__(self, settle_seconds: float = 2.0) -> None:
        self.settle_seconds = settle_seconds
        self._driver: webdriver.Firefox | None = None

    def __enter__(self) -> Browser:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._driver is not None:
            self._driver.quit()
            self._driver = None

    def _start(self) -> webdriver.Firefox:
        if self._driver is None:
            options = webdriver.FirefoxOptions()
            options.add_argument("-headless")
            # Don't wait for every ad and tracker to finish loading.
            options.page_load_strategy = "eager"
            self._driver = webdriver.Firefox(options=options)
            self._driver.set_page_load_timeout(45)
        return self._driver

    def render(self, url: str) -> tuple[str, str] | None:
        """Return the rendered (HTML, visible text) of a page, or None on failure."""
        driver = self._start()
        try:
            driver.get(url)
        except WebDriverException:
            pass  # A slow page can still have rendered its content.
        try:
            # Wait for scripts to finish filling in the page: poll until the
            # visible text stops changing, up to MAX_RENDER_SECONDS.
            text = ""
            deadline = time.monotonic() + MAX_RENDER_SECONDS
            while time.monotonic() < deadline:
                time.sleep(self.settle_seconds)
                previous, text = text, driver.find_element(By.TAG_NAME, "body").text
                if text and text == previous:
                    break
            return driver.page_source, text
        except WebDriverException:
            return None


def hours_from_periods(html: str) -> WeeklyHours | None:
    """Hours embedded as Google-style periods, e.g. in a Next.js data payload.

    The format is [{"open": {"day": 0, "hour": 8, "minute": 0}, "close": {...}}]
    with day 0 meaning Sunday.
    """
    text = html.replace('\\"', '"')
    start = text.find('"opening_hours":[')
    if start < 0:
        return None
    start = text.index("[", start)
    depth = 0
    for end in range(start, len(text)):
        depth += {"[": 1, "]": -1}.get(text[end], 0)
        if depth == 0:
            break
    try:
        periods = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    weekly: WeeklyHours = {}
    for period in periods:
        opens, closes = period.get("open", {}), period.get("close", {})
        if "hour" not in opens or "hour" not in closes:
            continue
        weekly.setdefault(WEEKDAYS[(opens["day"] - 1) % 7], []).append(
            f"{opens['hour']:02d}:{opens.get('minute', 0):02d}-"
            f"{closes['hour']:02d}:{closes.get('minute', 0):02d}"
        )
    return {day: weekly.get(day, []) for day in WEEKDAYS} if weekly else None


def _label(url: str, kind: str) -> str:
    """Describe where hours came from, flagging Wayback Machine copies."""
    if "web.archive.org" in url:
        return f"archived copy of vendor website ({kind}), may be outdated"
    return f"vendor website ({kind})"


def static_hours(url: str, address: str | None) -> VendorHours | None:
    """Hours from structured data in the page as served, without a browser."""
    html = None
    for as_browser in (True, False):
        try:
            html = fetch_html(url, as_browser=as_browser)
            break
        except FetchError:
            continue
    if html is None:
        return None
    weekly = hours_from_json_ld(html, address)
    if weekly:
        return VendorHours(_label(url, "schema.org data"), weekly=weekly)
    weekly = hours_from_periods(html)
    return VendorHours(_label(url, "embedded hours data"), weekly=weekly) if weekly else None


def html_to_text(html: str) -> str:
    """Page text including hidden elements (collapsed tabs, accordions), one block per line."""
    html = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|tr|section|span)>", "\n", html)
    text = unescape(re.sub(r"<[^>]+>", " ", html))
    return "\n".join(" ".join(line.split()) for line in text.splitlines())


def hours_page_link(html: str, base_url: str) -> str | None:
    """A same-site link that looks like an "hours" or "location & hours" page."""
    site = urlparse(base_url).netloc.removeprefix("www.")
    for href, label in re.findall(r'(?is)<a\b[^>]*href="([^"#]+)"[^>]*>(.*?)</a>', html):
        url = urljoin(base_url, unescape(href))
        same_site = urlparse(url).netloc.removeprefix("www.") == site
        if not same_site or url.rstrip("/") == base_url.rstrip("/"):
            continue
        if "hour" in href.lower() or "hour" in re.sub(r"<[^>]+>", "", label).lower():
            return url
    return None


def _hours_from_page(
    url: str, html: str, text: str, address: str | None
) -> VendorHours | None:
    weekly = hours_from_json_ld(html, address)
    if weekly:
        return VendorHours(_label(url, "schema.org data"), weekly=weekly)
    for candidate in (text, html_to_text(html)):
        lines = hours_from_text(candidate, address)
        if lines:
            return VendorHours(_label(url, "page text"), weekly=weekly_from_text(lines), text=lines)
    return None


def rendered_hours(browser: Browser, url: str, address: str | None) -> VendorHours | None:
    """Hours from the page after Firefox renders it, or from its "hours" subpage."""
    page = browser.render(url)
    if page is None:
        return None
    found = _hours_from_page(url, *page, address)
    if found is None:
        subpage_url = hours_page_link(page[0], url)
        subpage = browser.render(subpage_url) if subpage_url else None
        found = _hours_from_page(subpage_url or url, *subpage, address) if subpage else None
    return found
