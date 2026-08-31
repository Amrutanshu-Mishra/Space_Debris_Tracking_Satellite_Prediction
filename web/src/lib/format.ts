/**
 * Formatting helpers shared across the console. Numbers and times are the
 * whole interface (DESIGN.md §2), so their presentation lives in one place.
 */

/** Split an ISO-8601 UTC instant into `date` and `time` parts, dropping any
 * fractional seconds. `2026-08-27T11:05:06.4Z` -> `{ date: "2026-08-27",
 * time: "11:05:06Z" }`. The trailing `Z` is kept — it is the point. */
export function splitIsoUtc(iso: string): { date: string; time: string } {
  const [date, rest = ""] = iso.split("T");
  return { date, time: rest.replace(/\.\d+/, "") };
}

/** `2026-08-27 11:05:06Z` — the absolute form shown on hover. */
export function absoluteUtc(iso: string): string {
  const { date, time } = splitIsoUtc(iso);
  return time ? `${date} ${time}` : date;
}

/** Relative time to a TCA, e.g. `in 14h 22m`, `in 3d 4h`, `5d 2h ago`.
 * Past instants are rendered `… ago` rather than hidden — the mock fixture
 * and any real backlog both contain them. */
export function relativeToTca(iso: string, now: number = Date.now()): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "—";

  const past = t < now;
  let secs = Math.abs(t - now) / 1000;
  const days = Math.floor(secs / 86400);
  secs -= days * 86400;
  const hours = Math.floor(secs / 3600);
  secs -= hours * 3600;
  const mins = Math.floor(secs / 60);

  let core: string;
  if (days > 0) core = `${days}d ${hours}h`;
  else if (hours > 0) core = `${hours}h ${mins}m`;
  else if (mins > 0) core = `${mins}m`;
  else core = "<1m";

  return past ? `${core} ago` : `in ${core}`;
}

/** Compact count: thousands-separated up to 1e6, then one-significant-figure
 * exponential (`4.5e8`). Used for the catalogue funnel figures. */
export function formatCount(n: number): string {
  if (!Number.isFinite(n)) return "—";
  if (Math.abs(n) >= 1_000_000) return n.toExponential(1).replace("e+", "e");
  return n.toLocaleString("en-US");
}

/** Whole hours with an `h` suffix: `208 h`. */
export function hours(n: number): string {
  return `${Math.round(n)} h`;
}
