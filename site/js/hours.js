// Opening-hours logic: open/closed status, closing and opening times, and
// formatting for 12- and 24-hour clocks.
//
// Times are Date objects whose UTC fields hold Boston wall-clock time
// ("naive" times). Hours in the data are Boston-local, so this keeps every
// calculation independent of the visitor's own time zone and DST rules.

export const WEEKDAYS = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
];
export const ALWAYS_OPEN = "Open 24 hours";

const MINUTE = 60 * 1000;
const DAY = 24 * 60 * MINUTE;

/** The current time in Boston, to the minute. */
export function bostonNow() {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-US", {
      timeZone: "America/New_York",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    })
      .formatToParts(new Date())
      .map(({ type, value }) => [type, value]),
  );
  return new Date(
    Date.UTC(+parts.year, +parts.month - 1, +parts.day, +parts.hour, +parts.minute),
  );
}

/** Round up to the next multiple of `minutes`: 21:46 -> 22:00, 21:45 -> 21:45. */
export function roundUp(moment, minutes = 15) {
  const step = minutes * MINUTE;
  return new Date(Math.ceil(moment.getTime() / step) * step);
}

/** Parse a datetime-local value ("2026-10-09T02:30"); null if invalid. */
export function parseLocal(value) {
  const moment = new Date(`${value}Z`);
  return value && !Number.isNaN(moment.getTime()) ? moment : null;
}

/** Format for a datetime-local input. */
export const toLocalValue = (moment) => moment.toISOString().slice(0, 16);

export const weekdayName = (moment) => WEEKDAYS[(moment.getUTCDay() + 6) % 7];

const startOfDay = (moment) =>
  Date.UTC(moment.getUTCFullYear(), moment.getUTCMonth(), moment.getUTCDate());

/** "08:00-22:30" -> [480, 1350] minutes after midnight. */
function parsePeriod(period) {
  return period.split("-").map((time) => {
    const [hours, minutes] = time.split(":").map(Number);
    return hours * 60 + minutes;
  });
}

/**
 * When the period covering `moment` ends, or null if closed then.
 *
 * A period whose end is not after its start (such as 08:00-03:00) runs into
 * the next day, so the previous day's hours are checked too. "Open 24 hours"
 * counts as closing at the following midnight.
 */
export function closingTime(weekly, moment) {
  const day = startOfDay(moment);
  const now = (moment.getTime() - day) / MINUTE;
  const index = WEEKDAYS.indexOf(weekdayName(moment));

  for (const period of weekly[WEEKDAYS[index]] ?? []) {
    if (period === ALWAYS_OPEN) return new Date(day + DAY);
    const [start, end] = parsePeriod(period);
    if (start <= now && now < end) return new Date(day + end * MINUTE);
    if (end <= start && start <= now) return new Date(day + DAY + end * MINUTE);
  }
  for (const period of weekly[WEEKDAYS[(index + 6) % 7]] ?? []) {
    if (period === ALWAYS_OPEN) continue;
    const [start, end] = parsePeriod(period);
    if (now < end && end <= start) return new Date(day + end * MINUTE);
  }
  return null;
}

/** When the next period starts, if that is after `moment` but within `withinMs`. */
export function openingTime(weekly, moment, withinMs) {
  for (const offset of [0, 1]) {
    const day = startOfDay(moment) + offset * DAY;
    const name = weekdayName(new Date(day));
    for (const period of weekly[name] ?? []) {
      const start = period === ALWAYS_OPEN ? 0 : parsePeriod(period)[0];
      const opens = day + start * MINUTE;
      if (moment.getTime() < opens && opens <= moment.getTime() + withinMs) {
        return new Date(opens);
      }
    }
  }
  return null;
}

/**
 * Status at `moment` and when it next changes:
 * "open" | "closes_soon" (with the closing time), "opens_soon" (with the
 * opening time), "closed", or null when the hours are unknown.
 */
export function statusAt(weekly, moment, soonMs) {
  if (!weekly) return { status: null, changes: null };
  const closes = closingTime(weekly, moment);
  if (closes) {
    const status = closes - moment <= soonMs ? "closes_soon" : "open";
    return { status, changes: closes };
  }
  const opens = openingTime(weekly, moment, soonMs);
  if (opens) return { status: "opens_soon", changes: opens };
  return { status: "closed", changes: null };
}

/** "13:30" or "1:30 PM" from a naive Date or minutes after midnight. */
export function formatTime(value, clock) {
  const total =
    typeof value === "number" ? value : value.getUTCHours() * 60 + value.getUTCMinutes();
  const hours = Math.floor(total / 60) % 24;
  const minutes = total % 60;
  if (clock === "24h") {
    return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
  }
  const suffix = hours < 12 ? "AM" : "PM";
  return `${hours % 12 || 12}${minutes ? `:${String(minutes).padStart(2, "0")}` : ""} ${suffix}`;
}

/** "13:00-01:30" as "13:00 – 01:30" or "1 PM – 1:30 AM". */
export function formatPeriod(period, clock) {
  if (period === ALWAYS_OPEN) return period;
  const [start, end] = parsePeriod(period);
  return `${formatTime(start, clock)} – ${formatTime(end, clock)}`;
}

/** "Thursday, October 8 at 1:15 PM". */
export function formatMoment(moment, clock) {
  const date = moment.toLocaleDateString("en-US", {
    timeZone: "UTC",
    weekday: "long",
    month: "long",
    day: "numeric",
  });
  return `${date} at ${formatTime(moment, clock)}`;
}
