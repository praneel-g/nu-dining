"""HTTP helpers shared by the scrapers."""

from __future__ import annotations

import json
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0"
)


SCRAPER_USER_AGENT = "NortheasternDiningData/1.0"

# Extra attempts after a timeout or 5xx response.
RETRIES = 2


class FetchError(RuntimeError):
    """Raised when a remote resource cannot be retrieved."""


def _open(url: str, headers: dict[str, str]) -> bytes:
    """GET a URL, retrying timeouts and server errors but not 4xx responses."""
    for attempt in range(RETRIES + 1):
        try:
            with urlopen(Request(url, headers=headers), timeout=30) as response:
                body: bytes = response.read()
                return body
        except HTTPError as error:
            if error.code < 500 or attempt == RETRIES:
                raise FetchError(f"Could not fetch {url}: {error}") from error
        except (URLError, TimeoutError) as error:
            if attempt == RETRIES:
                raise FetchError(f"Could not fetch {url}: {error}") from error
        time.sleep(2 * (attempt + 1))
    raise AssertionError("unreachable")


def fetch_json(url: str, *, referer: str) -> Any:
    """Fetch and decode a JSON document."""
    body = _open(
        url,
        {
            "Accept": "application/json",
            "Referer": referer,
            "User-Agent": SCRAPER_USER_AGENT,
        },
    )
    return json.loads(body)


def fetch_husky_card_page(slug: str) -> str:
    """Rendered HTML content of a page on huskycard.northeastern.edu (WordPress)."""
    payload = fetch_json(
        f"https://huskycard.northeastern.edu/wp-json/wp/v2/pages?slug={slug}",
        referer=f"https://huskycard.northeastern.edu/{slug}/",
    )
    try:
        content: str = payload[0]["content"]["rendered"]
    except (IndexError, KeyError, TypeError) as error:
        raise FetchError(f"The Husky Card site returned no content for {slug!r}.") from error
    return content


def fetch_html(url: str, *, as_browser: bool = True) -> str:
    """Fetch a web page, by default identifying as a browser.

    Some sites block browser-like clients that aren't real browsers, so
    ``as_browser=False`` sends the scraper's own User-Agent instead.
    """
    agent = BROWSER_USER_AGENT if as_browser else SCRAPER_USER_AGENT
    body = _open(url, {"Accept": "text/html", "User-Agent": agent})
    return body.decode("utf-8", errors="replace")
