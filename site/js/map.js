// Map view: the filtered places plus the visitor's current location.
// Leaflet (global `L`) is loaded by index.html.

const NORTHEASTERN = [42.3398, -71.0892];

export function createMap(element, noteElement) {
  const map = L.map(element).setView(NORTHEASTERN, 15);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);
  const markers = L.layerGroup().addTo(map);

  let bounds = [];
  let you = null;
  let accuracy = null;
  let fittedFor = null;

  const fit = () => {
    const points = you ? [...bounds, you.getLatLng()] : bounds;
    if (points.length) map.fitBounds(points, { padding: [30, 30], maxZoom: 16 });
  };

  // A button that re-centers the map on the visitor.
  const LocateControl = L.Control.extend({
    options: { position: "topleft" },
    onAdd() {
      const button = L.DomUtil.create("button", "locate-button");
      button.type = "button";
      button.title = "Show my location";
      button.setAttribute("aria-label", "Show my location");
      button.textContent = "◎";
      L.DomEvent.disableClickPropagation(button);
      L.DomEvent.on(button, "click", () => {
        if (you) map.setView(you.getLatLng(), 16);
        else document.getElementById("location-notice").scrollIntoView({ block: "center" });
      });
      return button;
    },
  });
  map.addControl(new LocateControl());

  return {
    /**
     * Show `places`, each { location, popupHtml }. The map re-fits only when
     * `filterKey` (the filters) changes, so re-renders for location updates or
     * the passing time don't keep moving it.
     */
    render(places, filterKey) {
      // Read on every render so marker colors follow theme changes.
      const css = getComputedStyle(document.documentElement);
      const colors = {
        restaurant: css.getPropertyValue("--accent").trim(),
        market: css.getPropertyValue("--market").trim(),
      };
      markers.clearLayers();
      bounds = [];
      let missing = 0;
      for (const { location, popupHtml } of places) {
        if (location.latitude == null || location.longitude == null) {
          missing += 1;
          continue;
        }
        const position = [location.latitude, location.longitude];
        bounds.push(position);
        L.circleMarker(position, {
          radius: 8,
          color: "#fff",
          weight: 2,
          fillColor: colors[location.category],
          fillOpacity: 0.95,
        })
          .bindPopup(popupHtml)
          .addTo(markers);
      }
      const notes = [`${bounds.length} location${bounds.length === 1 ? "" : "s"} on the map.`];
      if (missing) notes.push(`${missing} couldn't be placed (no coordinates).`);
      noteElement.textContent = notes.join(" ");

      map.invalidateSize();
      if (filterKey !== fittedFor) {
        fittedFor = filterKey;
        fit();
      }
    },

    /** Show or move the "you are here" dot. */
    setPosition(coords) {
      const here = [coords.latitude, coords.longitude];
      if (you) {
        you.setLatLng(here);
        accuracy.setLatLng(here).setRadius(coords.accuracy);
        return;
      }
      accuracy = L.circle(here, { radius: coords.accuracy, weight: 1, fillOpacity: 0.1 }).addTo(map);
      you = L.circleMarker(here, {
        radius: 7,
        color: "#fff",
        weight: 3,
        fillColor: "#2b7bff",
        fillOpacity: 1,
      })
        .bindTooltip("You are here")
        .addTo(map);
      fit();
    },
  };
}
