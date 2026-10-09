// Service worker: makes the site installable and usable offline.
// Our own files are fetched network-first, so new data and code show up as
// soon as they're deployed, with the cached copy as an offline fallback.
// Versioned CDN files (Leaflet) are cache-first. Map tiles aren't cached.

const CACHE = "nu-dining-v1";
const SHELL = [
  "./",
  "index.html",
  "style.css",
  "manifest.webmanifest",
  "js/app.js",
  "js/hours.js",
  "js/location.js",
  "js/map.js",
  "js/settings.js",
  "data/dining_locations.json",
  "icons/icon-192.png",
];
const CDN_HOST = "cdnjs.cloudflare.com";

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.addAll(SHELL))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);

  if (url.origin === self.location.origin) {
    event.respondWith(networkFirst(request));
  } else if (url.hostname === CDN_HOST) {
    event.respondWith(cacheFirst(request));
  }
});

async function networkFirst(request) {
  const cache = await caches.open(CACHE);
  try {
    const response = await fetch(request);
    if (response.ok) cache.put(request, response.clone());
    return response;
  } catch (error) {
    // Ignore the query string so filtered URLs (?view=map…) work offline.
    const cached = await cache.match(request, { ignoreSearch: true });
    if (cached) return cached;
    if (request.mode === "navigate") {
      const shell = await cache.match("./");
      if (shell) return shell;
    }
    throw error;
  }
}

async function cacheFirst(request) {
  const cache = await caches.open(CACHE);
  const cached = await cache.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok || response.type === "opaque") cache.put(request, response.clone());
  return response;
}
