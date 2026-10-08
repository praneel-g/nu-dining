# Northeastern Dining

A static site showing where to eat at and around Northeastern: hours, open-now
filtering, a map, and which places take meal swipes or Dining Dollars.

- `dining/` scrapes Dine On Campus, the Husky Card vendor pages, vendor
  websites, and OpenStreetMap into `site/data/dining_locations.json`.
- `site/` is the static front end (plain HTML/JS + Leaflet) that reads that file.
- `.github/workflows/update-site.yml` re-scrapes every 12 hours, commits the
  new data, and deploys `site/` to GitHub Pages.

## Running locally

```sh
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m dining.scrape            # add --no-browser to skip Firefox/Selenium
python -m http.server -d site 8000 # then open http://localhost:8000
```

The browser fallback needs Firefox installed.

## GitHub setup

In the repository's **Settings → Pages**, set **Source** to **GitHub Actions**.
The workflow then runs on schedule, on manual dispatch, and on pushes to `main`
that touch `site/` or the workflow.
