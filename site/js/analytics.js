// Anonymous usage counts through GoatCounter (https://www.goatcounter.com):
// no cookies and no personal data. Counts one visit per page load, plus
// events for the features people use. Does nothing until GOATCOUNTER_CODE
// is set, and GoatCounter itself ignores localhost and bots.

// The site code chosen when signing up: https://<code>.goatcounter.com
const GOATCOUNTER_CODE = "";
const SCRIPT = {
  src: "https://gc.zgo.at/count.v5.js",
  integrity: "sha384-atnOLvQb9t+jTSipvd75X2yginT4PjVbqDdlJAmxMm+wYElFmeR6EmLP5bYeoRVQ",
};

// Events sent before the script has loaded wait here.
const queue = [];
let ready = false;

function send(count) {
  if (ready) window.goatcounter.count(count);
  else queue.push(count);
}

/** Count an event, such as "campus/oakland" or "view/map". */
export function trackEvent(name) {
  if (GOATCOUNTER_CODE) send({ path: name, title: name, event: true });
}

/** Load GoatCounter and count this visit as a view of `path`. */
export function initAnalytics(path) {
  if (!GOATCOUNTER_CODE) return;
  document.getElementById("analytics-note").hidden = false;
  const script = document.createElement("script");
  script.async = true;
  script.src = SCRIPT.src;
  script.integrity = SCRIPT.integrity;
  script.crossOrigin = "anonymous";
  script.dataset.goatcounter = `https://${GOATCOUNTER_CODE}.goatcounter.com/count`;
  // Counted by hand below, so filters in the query string (?view=map…)
  // don't split one page into many.
  script.dataset.goatcounterSettings = JSON.stringify({ no_onload: true });
  script.addEventListener("load", () => {
    ready = true;
    window.goatcounter.count({ path });
    for (const count of queue.splice(0)) window.goatcounter.count(count);
  });
  document.head.append(script);
}
