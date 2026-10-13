// Shared current-location handling for the map and the distance sort.
// Shows a notice in #location-notice whenever the location isn't available,
// including a button to ask for permission. Returns a controller whose
// setVisible() hides the notice while no view needs the location; the
// notice comes back, if still relevant, when one does again.
export function watchLocation(onPosition, { watch = false } = {}) {
  const notice = document.getElementById("location-notice");
  // Whether a view needs the location, and whether there's a problem to report.
  let visible = true;
  let pending = false;
  const controller = {
    setVisible(value) {
      visible = value;
      notice.hidden = !(visible && pending);
    },
  };

  const show = (message, withButton = false) => {
    pending = true;
    notice.hidden = !visible;
    notice.replaceChildren(document.createTextNode(message));
    if (withButton) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "notice-button";
      button.textContent = "Share my location";
      button.addEventListener("click", start);
      notice.append(" ", button);
    }
  };
  const hide = () => {
    pending = false;
    notice.hidden = true;
  };

  // True while a request is pending or succeeding, so a permission change
  // doesn't start a second watcher.
  let active = false;

  function start() {
    if (active) return;
    active = true;
    const success = (position) => {
      hide();
      onPosition(position.coords);
    };
    const failure = (error) => {
      active = false;
      if (error.code === error.PERMISSION_DENIED) {
        show(
          "Location access is blocked for this site. Allow it in your browser's site " +
            "settings (the icon next to the address bar), then reload.",
        );
      } else {
        show("Couldn't determine your location right now.", true);
      }
    };
    const options = { enableHighAccuracy: true, timeout: 15000 };
    if (watch) navigator.geolocation.watchPosition(success, failure, options);
    else navigator.geolocation.getCurrentPosition(success, failure, options);
  }

  if (!window.isSecureContext) {
    show("Location only works over HTTPS or on localhost.");
    return controller;
  }
  if (!("geolocation" in navigator)) {
    show("This browser can't share its location.");
    return controller;
  }
  if (!navigator.permissions) {
    start();
    return controller;
  }
  navigator.permissions
    .query({ name: "geolocation" })
    .then((status) => {
      const react = () => {
        if (status.state === "granted") start();
        else if (status.state === "denied") {
          show(
            "Location access is blocked for this site. Allow it in your browser's site " +
              "settings (the icon next to the address bar), then reload.",
          );
        } else {
          show("Location access hasn't been granted yet.", true);
          start(); // Also triggers the browser's own permission prompt.
        }
      };
      status.addEventListener("change", react);
      react();
    })
    .catch(start);
  return controller;
}
