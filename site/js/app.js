// Loads the scraped data and renders the list or map for the chosen filters.
// Filters live in the URL query string, so filtered views can be shared.

import {
  WEEKDAYS,
  bostonNow,
  formatMoment,
  formatPeriod,
  formatTime,
  parseLocal,
  periodStart,
  roundUp,
  statusAt,
  toLocalValue,
  weekdayName,
} from "./hours.js";
import { watchLocation } from "./location.js";
import { createMap } from "./map.js";

const DATA_URL = "data/dining_locations.json";

const CATEGORIES = { restaurants: "Restaurants & cafés", markets: "Markets" };
const PAYMENTS = { meal_swipes: "Meal swipes", dining_dollars: "Dining Dollars" };
const STATUS_LABELS = {
  open: "Open until",
  closes_soon: "Closes soon ·",
  opens_soon: "Opens soon ·",
};
// Statuses that count as open when filtering by time.
const OPEN_STATUSES = new Set(["open", "closes_soon", "opens_soon"]);
// How close to opening or closing a place gets an "opens/closes soon" tag.
const SOON_MS = 30 * 60 * 1000;

// Allowed values for each filter; the first is the default.
const FILTERS = {
  category: ["", "restaurants", "markets"],
  payment: ["", "meal_swipes", "dining_dollars"],
  when: ["now", "any", "at"],
  view: ["list", "map"],
  sort: ["name", "opening", "closing", "distance"],
  clock: ["12h", "24h"],
};

const form = document.getElementById("filters");
const elements = {
  intro: document.getElementById("intro"),
  sources: document.getElementById("sources"),
  summary: document.getElementById("summary"),
  list: document.getElementById("list-view"),
  mapView: document.getElementById("map-view"),
  map: document.getElementById("map"),
  mapNote: document.getElementById("map-note"),
};

let data = null;
let map = null;
let coords = null;
let locating = false;
let lastReference = null;

const state = readState();

function readState() {
  const params = new URLSearchParams(window.location.search);
  const result = {};
  for (const [name, allowed] of Object.entries(FILTERS)) {
    const value = params.get(name) ?? allowed[0];
    result[name] = allowed.includes(value) ? value : allowed[0];
  }
  result.at = params.get("at") ?? "";
  return result;
}

function writeState() {
  const params = new URLSearchParams();
  for (const [name, allowed] of Object.entries(FILTERS)) {
    if (state[name] !== allowed[0]) params.set(name, state[name]);
  }
  if (state.when === "at" && state.at) params.set("at", state.at);
  const query = params.toString();
  history.replaceState(null, "", query ? `?${query}` : window.location.pathname);
}

const escape = (text) =>
  String(text ?? "").replace(
    /[&<>"']/g,
    (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char],
  );

/** Miles between two points. */
function miles(lat1, lon1, lat2, lon2) {
  const rad = Math.PI / 180;
  const a =
    Math.sin(((lat2 - lat1) * rad) / 2) ** 2 +
    Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(((lon2 - lon1) * rad) / 2) ** 2;
  return 3958.8 * 2 * Math.asin(Math.sqrt(a));
}

/** A location plus its status, hours, and distance at `reference`. */
function describe(location, reference) {
  const weekly = location.weekly_hours;
  const { status, changes } = statusAt(weekly, reference, SOON_MS);
  const hasCoords = location.latitude != null && location.longitude != null;
  return {
    location,
    status,
    changes,
    opens: weekly ? periodStart(weekly, reference) : null,
    dayHours: weekly ? (weekly[weekdayName(reference)] ?? []) : null,
    distance:
      coords && hasCoords
        ? miles(coords.latitude, coords.longitude, location.latitude, location.longitude)
        : null,
  };
}

function compare(a, b) {
  const byName = a.location.name.localeCompare(b.location.name, undefined, {
    sensitivity: "base",
  });
  if (state.sort === "opening") {
    // Open places by when they opened, then the rest by how soon they open.
    return (a.opens ?? Infinity) - (b.opens ?? Infinity) || byName;
  }
  if (state.sort === "closing") {
    // Open places by soonest closing, then ones opening soon, then the rest.
    const rank = (item) => ({ open: 0, closes_soon: 0, opens_soon: 1 })[item.status] ?? 2;
    return rank(a) - rank(b) || (a.changes ?? 0) - (b.changes ?? 0) || byName;
  }
  if (state.sort === "distance" && coords) {
    return (a.distance ?? Infinity) - (b.distance ?? Infinity) || byName;
  }
  return byName;
}

const periodsHtml = (periods) =>
  periods.map((period) => `<span class="period">${escape(formatPeriod(period, state.clock))}</span>`).join(", ");

function hoursHtml(item, day) {
  let statusTag = "";
  if (item.status in STATUS_LABELS) {
    statusTag = `<span class="status status-${item.status}">${escape(STATUS_LABELS[item.status])} ${escape(formatTime(item.changes, state.clock))}</span> `;
  } else if (item.status === "closed" && item.opens && state.sort === "opening") {
    // Name the day when it isn't the one whose hours are shown.
    const opensDay = weekdayName(item.opens);
    const when = `${opensDay === day ? "" : `${opensDay.slice(0, 3)} `}${formatTime(item.opens, state.clock)}`;
    statusTag = `<span class="status status-opens">Opens ${escape(when)}</span> `;
  }
  let hours;
  if (item.dayHours === null) {
    hours = item.location.hours_text
      ? escape(item.location.hours_text.join(" · "))
      : '<span class="muted">Hours unavailable</span>';
  } else if (item.dayHours.length) {
    hours = periodsHtml(item.dayHours);
  } else {
    hours = '<span class="closed">Closed</span>';
  }
  return `${statusTag}<span class="day">${escape(day.slice(0, 3))}</span> ${hours}`;
}

function cardHtml(item, day) {
  const loc = item.location;
  const onCampus = loc.source !== "Husky Card off-campus vendors";
  const name = loc.url
    ? `<a href="${escape(loc.url)}" target="_blank" rel="noopener">${escape(loc.name)}</a>`
    : escape(loc.name);
  const distance = item.distance != null ? ` <span class="distance">· ${item.distance.toFixed(1)} mi</span>` : "";
  const payments = loc.payment.length
    ? `<ul class="payments">${loc.payment.map((method) => `<li>${escape(PAYMENTS[method])}</li>`).join("")}</ul>`
    : '<p class="muted">Payment methods unknown</p>';
  const weekly = loc.weekly_hours
    ? `<details>
        <summary>Weekly hours</summary>
        <table>${WEEKDAYS.map(
          (weekday) => `<tr><th scope="row">${weekday.slice(0, 3)}</th>
            <td>${loc.weekly_hours[weekday]?.length ? periodsHtml(loc.weekly_hours[weekday]) : "Closed"}</td></tr>`,
        ).join("")}</table>
        ${loc.hours_source ? `<p class="source">Source: ${escape(loc.hours_source)}</p>` : ""}
      </details>`
    : "";
  return `<article class="card">
    <div class="card-head">
      <h3>${name}</h3>
      <span class="tag ${onCampus ? "tag-on" : "tag-off"}">${onCampus ? "On campus" : "Off campus"}</span>
    </div>
    ${loc.address || distance ? `<p class="address">${escape(loc.address)}${distance}</p>` : ""}
    <p class="today">${hoursHtml(item, day)}</p>
    ${payments}
    ${weekly}
  </article>`;
}

function popupHtml(item, day) {
  const loc = item.location;
  const name = loc.url
    ? `<a href="${escape(loc.url)}" target="_blank" rel="noopener">${escape(loc.name)}</a>`
    : escape(loc.name);
  const payments =
    loc.payment.map((method) => PAYMENTS[method]).join(", ") || "Payment methods unknown";
  return `<strong>${name}</strong><br>${escape(loc.address)}<br>${hoursHtml(item, day)}<br><small>${escape(payments)}</small>`;
}

/** Ask for the visitor's location once, the first time a view needs it. */
function ensureLocation() {
  if (locating) return;
  locating = true;
  watchLocation(
    (position) => {
      // Small GPS jitter only moves the map dot; re-rendering the list would
      // also collapse any open "Weekly hours" panels.
      const moved =
        !coords ||
        miles(coords.latitude, coords.longitude, position.latitude, position.longitude) > 0.03;
      coords = position;
      map?.setPosition(position);
      if (moved) render();
    },
    { watch: true },
  );
}

function syncForm(reference) {
  for (const name of Object.keys(FILTERS)) {
    for (const input of form.elements[name]) input.checked = input.value === state[name];
  }
  const timeInput = form.elements.at;
  timeInput.disabled = state.when !== "at";
  if (document.activeElement !== timeInput) timeInput.value = toLocalValue(reference);
}

function render() {
  if (!data) return;
  const now = roundUp(bostonNow());
  const reference = state.when === "at" ? (parseLocal(state.at) ?? now) : now;
  const moment = state.when === "any" ? null : reference;
  const day = weekdayName(reference);
  lastReference = now.getTime();
  syncForm(reference);

  const sections = [];
  let unknownHours = 0;
  for (const [key, label] of Object.entries(CATEGORIES)) {
    if (state.category && state.category !== key) continue;
    const items = [];
    for (const location of data[key]) {
      if (state.payment && !location.payment.includes(state.payment)) continue;
      const item = describe(location, reference);
      if (moment && !OPEN_STATUSES.has(item.status)) {
        if (item.status === null) unknownHours += 1;
        continue;
      }
      items.push(item);
    }
    items.sort(compare);
    sections.push({ label, items });
  }

  // Summary line.
  let summary = moment
    ? `Showing places open on <strong>${escape(formatMoment(moment, state.clock))}</strong>.`
    : `Showing all places, with ${escape(day)}'s hours.`;
  if (moment && unknownHours) {
    summary += ` ${unknownHours} with unknown hours hidden — <button type="button" class="link-button" data-show-all>show all</button>.`;
  }
  if (state.sort === "distance") {
    summary += coords ? " Sorted by distance from you." : " Waiting for your location to sort by distance…";
  }
  elements.summary.innerHTML = summary;

  const needsLocation = state.sort === "distance" || state.view === "map";
  if (needsLocation) ensureLocation();

  elements.list.hidden = state.view !== "list";
  elements.mapView.hidden = state.view !== "map";
  if (state.view === "list") {
    elements.list.innerHTML = sections
      .map(
        ({ label, items }) => `<section class="section">
          <h2>${escape(label)} <span class="count">${items.length}</span></h2>
          ${items.length ? "" : '<p class="muted">Nothing matches these filters.</p>'}
          <div class="grid">${items.map((item) => cardHtml(item, day)).join("")}</div>
        </section>`,
      )
      .join("");
  } else {
    map ??= createMap(elements.map, elements.mapNote);
    if (coords) map.setPosition(coords);
    const places = sections.flatMap(({ items }) =>
      items.map((item) => ({ location: item.location, popupHtml: popupHtml(item, day) })),
    );
    map.render(places, JSON.stringify(state));
  }
}

function sourceLinks(sources) {
  // One link per site, even when several pages of a site were scraped.
  const sites = new Map();
  for (const url of sources) {
    const host = new URL(url).host;
    if (!sites.has(host)) sites.set(host, url);
  }
  return [...sites]
    .map(([host, url]) => `<a href="${escape(url)}">${escape(host)}</a>`)
    .join(" and ");
}

form.addEventListener("change", (event) => {
  const { name, value } = event.target;
  if (name === "at") {
    state.at = value;
  } else if (name in FILTERS) {
    state[name] = value;
    // Choosing "Open at…" enables the time picker; results update once a time is picked.
    if (name === "when" && value === "at") {
      state.at ||= form.elements.at.value;
      form.elements.at.disabled = false;
      form.elements.at.focus();
    }
  }
  writeState();
  render();
});
form.addEventListener("submit", (event) => event.preventDefault());

elements.summary.addEventListener("click", (event) => {
  if (!event.target.matches("[data-show-all]")) return;
  state.when = "any";
  writeState();
  render();
});

// "Now" moves on: re-render when the rounded current time changes.
setInterval(() => {
  if (state.when === "now" && roundUp(bostonNow()).getTime() !== lastReference) {
    render();
  }
}, 60 * 1000);

fetch(DATA_URL, { cache: "no-cache" })
  .then((response) => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  })
  .then((loaded) => {
    data = loaded;
    elements.sources.innerHTML = `Data scraped ${escape(data.retrieved_on)} from ${sourceLinks(data.sources)}.`;
    form.hidden = false;
    render();
  })
  .catch((error) => {
    elements.sources.textContent = `Couldn't load the dining data (${error.message}).`;
  });
