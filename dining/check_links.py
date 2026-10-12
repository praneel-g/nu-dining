"""Check every website and menu link in the data files and report problems.

Run weekly by .github/workflows/check-links.yml. It only reports: fix a
link through ``WEBSITE_FIXES`` (husky_vendors.py) or the menu tables in
menus.py. Exits with status 1 when a link is broken or looks unsafe, so
the workflow run fails and GitHub sends a notification.
"""

from __future__ import annotations

import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from .models import DATA_FILE, OAKLAND_DATA_FILE, DiningData
from .net import BROWSER_USER_AGENT

# Cloudflare blocks automated visits, and these links are built from slugs
# that come straight from the Dine On Campus API.
SKIPPED_HOSTS = ("dineoncampus.com",)
# Responses that mean "go away, robot" rather than "this page is gone".
BLOCKED_STATUSES = {401, 403, 429}
PARKED_HOSTS = re.compile(r"(^|\.)(forsale\.godaddy|sedo|dan|afternic|hugedomains)\.com$")
PARKED_TEXT = re.compile(
    r"domain (?:name )?(?:\S+ )?is for sale|buy this domain|this domain may be for sale",
    re.IGNORECASE,
)
# A script before the document itself is a classic sign of a hacked site.
INJECTED_SCRIPT = re.compile(r"^\s*<script\b[^>]*>.*?(?=<!doctype|<html)", re.IGNORECASE | re.DOTALL)
# A near-empty page that only redirects by script, as parked domains do
# ("/lander" on GoDaddy).
SCRIPT_REDIRECT = re.compile(r"""window\.location(?:\.href)?\s*=\s*["']([^"']+)""")
CLOUDFLARE_BLOCK = re.compile(r"Attention Required! \| Cloudflare|cf-error-details")


@dataclass
class Result:
    """The outcome of checking one link."""

    url: str
    used_by: list[str]
    problem: str | None = None  # Broken or unsafe: needs fixing.
    unchecked: str | None = None  # Couldn't tell, such as a bot block.


def collect_links() -> dict[str, list[str]]:
    """Every checkable link, mapped to the places and fields that use it."""
    links: dict[str, list[str]] = {}
    for campus, path in (("Boston", DATA_FILE), ("Oakland", OAKLAND_DATA_FILE)):
        data: DiningData = json.loads(path.read_text(encoding="utf-8"))
        for location in data["restaurants"] + data["markets"]:
            for field, label in (("url", "website"), ("menu_url", "menu")):
                url = location.get(field)
                if isinstance(url, str) and not urlparse(url).netloc.endswith(SKIPPED_HOSTS):
                    links.setdefault(url, []).append(f"{location['name']} ({campus} {label})")
    return links


def check(url: str, used_by: list[str], fetch_url: str | None = None) -> Result:
    """Fetch one link (or the page it redirects to by script) and classify it."""
    result = Result(url, used_by)
    headers = {"User-Agent": BROWSER_USER_AGENT, "Accept": "text/html"}
    request = Request(fetch_url or url, headers=headers)
    try:
        with urlopen(request, timeout=30) as response:
            final_url = response.url
            html = response.read(500_000).decode("utf-8", errors="replace")
    except HTTPError as error:
        body = error.read(20_000).decode("utf-8", errors="replace")
        if error.code in BLOCKED_STATUSES or CLOUDFLARE_BLOCK.search(body):
            result.unchecked = f"blocked automated checks (HTTP {error.code})"
        else:
            result.problem = f"HTTP {error.code}"
        return result
    except TimeoutError:
        result.unchecked = "timed out"
        return result
    except URLError as error:
        if isinstance(error.reason, TimeoutError):
            result.unchecked = "timed out"
        else:
            result.problem = f"unreachable ({error.reason})"
        return result
    except OSError as error:
        result.problem = f"unreachable ({error})"
        return result

    redirect = SCRIPT_REDIRECT.search(html)
    if redirect and len(html) < 2_000 and fetch_url is None:
        target = urljoin(final_url, redirect.group(1))
        if urlparse(target).path.rstrip("/") == "/lander":
            result.problem = f"parked domain (redirects to {target})"
            return result
        return check(url, used_by, target)
    if PARKED_HOSTS.search(urlparse(final_url).netloc) or PARKED_TEXT.search(html):
        result.problem = f"parked domain or for sale (ends at {final_url})"
    elif match := INJECTED_SCRIPT.search(html):
        sources = re.findall(r'src=["\']([^"\']+)', match.group(0))
        result.problem = "script injected before the page: " + (", ".join(sources) or "inline")
    elif CLOUDFLARE_BLOCK.search(html):
        result.unchecked = "blocked automated checks (Cloudflare)"
    return result


def report(results: list[Result]) -> str:
    """A Markdown summary of the problems and the links that couldn't be checked."""
    problems = [result for result in results if result.problem]
    unchecked = [result for result in results if result.unchecked]
    lines = [
        f"# Link check: {len(problems)} problem(s), {len(unchecked)} unchecked, "
        f"{len(results)} links",
        "",
    ]
    for title, group, reason in (
        ("Needs fixing", problems, "problem"),
        ("Couldn't check (look at these by hand)", unchecked, "unchecked"),
    ):
        if group:
            lines += [f"## {title}", ""]
            lines += [
                f"- {', '.join(result.used_by)}: <{result.url}> — {getattr(result, reason)}"
                for result in group
            ]
            lines.append("")
    if not problems:
        lines.append("All checked links work.")
    return "\n".join(lines)


def main() -> None:
    """Check every link, print the report, and fail if anything needs fixing."""
    links = collect_links()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda item: check(*item), links.items()))
    summary = report(results)
    print(summary)
    if path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(path, "a", encoding="utf-8") as file:
            file.write(summary + "\n")
    sys.exit(1 if any(result.problem for result in results) else 0)


if __name__ == "__main__":
    main()
