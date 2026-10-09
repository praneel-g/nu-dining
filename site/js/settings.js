// Display preferences in the header: color theme and 12/24-hour clock.
// Saved in this browser only; the page works the same if storage is blocked.

function read(key) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key, value) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    // Storage unavailable (private mode, blocked site data): not saved.
  }
}

export const settings = {
  theme: ["light", "dark"].includes(read("theme")) ? read("theme") : "auto",
  clock: read("clock") === "24h" ? "24h" : "12h",
};

function applyTheme() {
  if (settings.theme === "auto") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = settings.theme;
}

/** Wire up the header controls; `onChange` runs after either one changes. */
export function initSettings(onChange) {
  const form = document.getElementById("settings");
  form.elements.theme.value = settings.theme;
  form.elements.clock.checked = settings.clock === "24h";
  applyTheme();

  form.addEventListener("change", (event) => {
    const { name } = event.target;
    if (name === "theme") {
      settings.theme = event.target.value;
      write("theme", settings.theme === "auto" ? null : settings.theme);
      applyTheme();
    } else if (name === "clock") {
      settings.clock = event.target.checked ? "24h" : "12h";
      write("clock", settings.clock === "24h" ? "24h" : null);
    }
    onChange();
  });
  form.addEventListener("submit", (event) => event.preventDefault());
}
