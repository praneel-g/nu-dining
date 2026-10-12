"""Menu links for places that Dine On Campus has no menu for.

Chains get their official menu page. Other places get the "Menu" link
from their own website, fetched plainly first and rendered in a browser
for sites that build their pages with JavaScript or block plain clients.
"""

from __future__ import annotations

import re
from html import unescape
from urllib.parse import urljoin, urlparse

from ..models import Location
from ..net import FetchError, fetch_html
from .vendor_sites import Browser

# Chain counters on campus have no website of their own in the data, and
# some chain sites block scrapers, so these are checked first.
CHAIN_MENUS = (
    (re.compile(r"\bstarbucks\b", re.IGNORECASE), "https://www.starbucks.com/menu"),
    (re.compile(r"\bsubway\b", re.IGNORECASE), "https://www.subway.com/en-us/menunutrition/menu"),
    (re.compile(r"\bpanera\b", re.IGNORECASE), "https://www.panerabread.com/en-us/menu.html"),
    (
        re.compile(r"\bmodern market\b", re.IGNORECASE),
        "https://modernmarket.com/menus/restaurant-menu/",
    ),
    (re.compile(r"\bwings over\b", re.IGNORECASE), "https://wingsover.com/menu/"),
)

# Menus for places with no website to find one on.
PLACE_MENUS = {
    "Poke Station": "https://places.singleplatform.com/poke-station-and-kitchen/menu",
}

LINK_PATTERN = re.compile(r'(?is)<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>')
MENU_WORD = re.compile(r"\bmenus?\b", re.IGNORECASE)
# Menus for something other than eating in.
OTHER_MENUS = re.compile(r"catering|gift|wholesale", re.IGNORECASE)


def chain_menu(name: str) -> str | None:
    """The official menu page of a chain, if ``name`` is one."""
    for pattern, url in CHAIN_MENUS:
        if pattern.search(name):
            return url
    return None


def menu_link(html: str, base_url: str) -> str | None:
    """The page's best link to a menu, or None.

    A link labeled "Menu" that also points at a menu URL wins, then one with
    either; same-site links beat ordering services. Ties go to the first.
    """
    site = urlparse(base_url).netloc.removeprefix("www.")
    best: tuple[int, str] | None = None
    for href, label in LINK_PATTERN.findall(html):
        href = unescape(href)
        label = " ".join(unescape(re.sub(r"<[^>]+>", " ", label)).split())
        if href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        if OTHER_MENUS.search(href) or OTHER_MENUS.search(label):
            continue
        url = urljoin(base_url, href)
        path = urlparse(url).path.lower()
        score = 2 * bool(MENU_WORD.search(label)) + 2 * ("menu" in path)
        if not score:
            continue
        score += urlparse(url).netloc.removeprefix("www.") == site
        if best is None or score > best[0]:
            best = (score, url)
    return best[1] if best else None


def site_menu(url: str, browser: Browser | None) -> str | None:
    """The menu link on a place's website, if it has one."""
    if "menu" in urlparse(url).path.lower():
        return url  # The listed website is already the menu.
    try:
        found = menu_link(fetch_html(url), url)
    except FetchError:
        found = None
    if found is None and browser is not None:
        rendered = browser.render(url)
        if rendered:
            found = menu_link(rendered[0], url)
    return found


def add_menu_links(locations: list[Location], use_browser: bool) -> None:
    """Fill ``menu_url`` for restaurants and cafés that have none yet.

    Markets are skipped: a grocery store's "menu" isn't what people want.
    """
    needed = [
        location
        for location in locations
        if location["category"] == "restaurant" and not location.get("menu_url")
    ]
    with Browser() as browser:
        for location in needed:
            url = location["url"]
            found = PLACE_MENUS.get(location["name"]) or chain_menu(location["name"])
            # Dine On Campus pages were already checked for menus.
            if found is None and url and "dineoncampus.com" not in url:
                found = site_menu(url, browser if use_browser else None)
            location["menu_url"] = found
