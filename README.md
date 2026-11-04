# Northeastern Dining

**[praneel-g.github.io/nu-dining](https://praneel-g.github.io/nu-dining/)**

Where to eat at and around Northeastern, on one page: what's open right now,
when places close, which ones take meal swipes or Dining Dollars, and how to
get there. Covers on-campus dining and Husky Card restaurants near the Boston
campus, plus the Oakland campus.

> This is an unofficial student project, not affiliated with or endorsed by
> Northeastern University or Dine On Campus. Hours come from public sources
> and can be wrong or out of date, especially around holidays and breaks. For
> anything important, check [nudining.com](https://nudining.com/public/hours-of-operation).

## What you can do

- **See what's open now**, or what will be open at a time you pick, with
  "closes soon" and "opens soon" tags.
- **Filter** by meal swipes or Dining Dollars, by restaurants or markets, and
  search by name.
- **Sort** A–Z, by opening or closing time, or by distance from you.
- **Use the map**, and get walking directions to any place in one tap.
- **Switch campuses** between Boston and Oakland.
- **Share a view**: filters live in the link, so a link to "open now, meal
  swipes, sorted by distance" opens exactly that.
- **Install it** on your phone's home screen. It also works offline with the
  last data it loaded.

## Found a mistake?

Wrong hours, a place in the wrong spot, or a broken link:
[open an issue](https://github.com/praneel-g/nu-dining/issues) with the place's
name and what's wrong. A screenshot or link to the correct information helps.

## Privacy

The site has no accounts, no ads, and no cookies. If you share your location
to sort by distance or show yourself on the map, it stays in your browser.
Map images load from OpenStreetMap, and Directions open in Google Maps. The
site may count visits anonymously through
[GoatCounter](https://www.goatcounter.com), which uses no cookies and
collects no personal data.

## How it works

The site is static: plain HTML, CSS, and JavaScript, with
[Leaflet](https://leafletjs.com) for the map, hosted on GitHub Pages. Twice a
day, a GitHub Actions workflow collects the data and redeploys the site:

| Data | Source |
|---|---|
| On-campus hours, addresses, and payments | [Dine On Campus](https://nudining.com) |
| Husky Card restaurants and payment options | Husky Card Services' vendor pages and map |
| Off-campus hours | Each vendor's website, or [OpenStreetMap](https://www.openstreetmap.org) when the website has none |
| Map positions | The sources above, OpenStreetMap, and Nominatim geocoding |

The page footer shows when the data was last updated. Hours that haven't
been confirmed for a while are marked on their card.

## Development

```sh
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m dining.scrape            # add --no-browser to skip Firefox/Selenium
python -m http.server -d site 8000 # then open http://localhost:8000
```

Some vendor sites are read with Firefox through Selenium, so the full scrape
needs Firefox installed. To work on the front end alone, skip the scrape and
serve `site/` as is; it reads the committed data.

Published data comes from the scheduled workflow. Please don't commit data
files from a local scrape: the schedule API's hours have sometimes disagreed
with the public hours page, and the workflow's data is the one that gets
checked.

### Layout

- `dining/` is the scraper. `python -m dining.scrape` writes
  `site/data/dining_locations.json` (Boston) and
  `site/data/oakland_dining_locations.json` (Oakland).
- `site/` is the front end, which reads those two files.
- `.github/workflows/update-site.yml` scrapes every 12 hours, commits the new
  data, and deploys `site/` to GitHub Pages.
- `.github/workflows/check-links.yml` checks every website and menu link
  weekly (`python -m dining.check_links`) and fails when one is broken,
  parked, or looks hacked.

### Fixing data by hand

When a source is wrong, fix it in the scraper so the next scrape keeps it:

- **Websites:** `WEBSITE_FIXES` in `dining/sources/husky_vendors.py`.
- **Menu links:** the tables in `dining/sources/menus.py`.
- **Addresses and map pins** for campus places:
  `ADDRESS_FIXES` and `BOSTON_BUILDINGS` in `dining/sources/dine_on_campus.py`.
- **Hours** for campus places: `CHECKED_HOURS` in the same file, copied
  from the public hours page and keyed by the page's "Week of" date.

### Running your own copy

Fork the repository, then in **Settings → Pages** set **Source** to **GitHub
Actions**. The workflow runs on its schedule, on manual dispatch, and on
pushes to `main` that touch `site/` or the workflow.
