/**
 * URL <-> view-state for the conjunction list: sort and filters. A filtered,
 * sorted view is fully described by the query string, so it can be shared and
 * survives reload (frontend brief). Pure functions only — no React here.
 */

import type { ConjunctionEvent, RiskTier } from "../api/types";

export type SortKey =
  | "tca"
  | "primary"
  | "secondary"
  | "miss_distance_km"
  | "relative_velocity_km_s"
  | "risk_score"
  | "confidence";

export type SortDir = "asc" | "desc";

export interface SortState {
  key: SortKey;
  dir: SortDir;
}

export interface Filters {
  /** Selected tiers; empty means "all tiers". */
  tiers: RiskTier[];
  /** Upper bound on time-to-TCA, in hours from now. `null` = no bound.
   *  Past events always pass an upper bound, so this never blanks a backlog. */
  windowHours: number | null;
  /** Inclusive lower bound on `risk_score`, 0..1. */
  minScore: number;
}

export const ALL_TIERS: readonly RiskTier[] = ["GREEN", "AMBER", "RED"];
export const WINDOW_CHOICES: readonly (number | null)[] = [6, 24, 72, 168, null];

export const DEFAULT_SORT: SortState = { key: "tca", dir: "asc" };
export const DEFAULT_FILTERS: Filters = { tiers: [], windowHours: null, minScore: 0 };

const SORT_KEYS: ReadonlySet<string> = new Set<SortKey>([
  "tca",
  "primary",
  "secondary",
  "miss_distance_km",
  "relative_velocity_km_s",
  "risk_score",
  "confidence",
]);

/** Natural first-click direction for a column: names/time ascending, magnitudes
 * descending (an operator clicking "risk" wants the worst first). */
export function defaultDirFor(key: SortKey): SortDir {
  return key === "tca" || key === "primary" || key === "secondary" ? "asc" : "desc";
}

/** Clicking a header: toggle direction if it is already the sort key, else
 * switch to that key at its natural direction. */
export function toggleSort(current: SortState, key: SortKey): SortState {
  if (current.key === key) return { key, dir: current.dir === "asc" ? "desc" : "asc" };
  return { key, dir: defaultDirFor(key) };
}

function isSortKey(v: string | null): v is SortKey {
  return v !== null && SORT_KEYS.has(v);
}

function isTier(v: string): v is RiskTier {
  return v === "GREEN" || v === "AMBER" || v === "RED";
}

export function parseQuery(params: URLSearchParams): { sort: SortState; filters: Filters } {
  const rawSort = params.get("sort");
  const sort: SortState = isSortKey(rawSort)
    ? { key: rawSort, dir: params.get("dir") === "desc" ? "desc" : params.get("dir") === "asc" ? "asc" : defaultDirFor(rawSort) }
    : DEFAULT_SORT;

  const tiers = (params.get("tier") ?? "")
    .split(",")
    .map((s) => s.trim().toUpperCase())
    .filter(isTier);

  const rawWindow = params.get("window");
  const windowHours =
    rawWindow === null || rawWindow === "all" ? null : Number.isFinite(Number(rawWindow)) ? Number(rawWindow) : null;

  const rawMin = Number(params.get("min"));
  const minScore = Number.isFinite(rawMin) ? Math.min(1, Math.max(0, rawMin)) : 0;

  return { sort, filters: { tiers: dedupeTiers(tiers), windowHours, minScore } };
}

function dedupeTiers(tiers: RiskTier[]): RiskTier[] {
  return ALL_TIERS.filter((t) => tiers.includes(t));
}

/** Merge new sort/filters into an existing params object, dropping anything at
 * its default so shared URLs stay short. */
export function writeQuery(
  prev: URLSearchParams,
  next: { sort?: SortState; filters?: Filters },
): URLSearchParams {
  const params = new URLSearchParams(prev);

  if (next.sort) {
    const { key, dir } = next.sort;
    if (key === DEFAULT_SORT.key && dir === DEFAULT_SORT.dir) {
      params.delete("sort");
      params.delete("dir");
    } else {
      params.set("sort", key);
      params.set("dir", dir);
    }
  }

  if (next.filters) {
    const { tiers, windowHours, minScore } = next.filters;
    if (tiers.length === 0) params.delete("tier");
    else params.set("tier", dedupeTiers(tiers).join(","));

    if (windowHours === null) params.delete("window");
    else params.set("window", String(windowHours));

    if (minScore <= 0) params.delete("min");
    else params.set("min", String(minScore));
  }

  return params;
}

export function applyFilters(
  events: readonly ConjunctionEvent[],
  filters: Filters,
  now: number = Date.now(),
): ConjunctionEvent[] {
  const cutoff = filters.windowHours === null ? null : now + filters.windowHours * 3_600_000;
  return events.filter((e) => {
    if (filters.tiers.length > 0 && !filters.tiers.includes(e.risk_tier)) return false;
    if (e.risk_score < filters.minScore) return false;
    if (cutoff !== null && Date.parse(e.tca) > cutoff) return false;
    return true;
  });
}

function compare(a: ConjunctionEvent, b: ConjunctionEvent, key: SortKey): number {
  switch (key) {
    case "tca":
      return Date.parse(a.tca) - Date.parse(b.tca);
    case "primary":
      return a.primary.name.localeCompare(b.primary.name);
    case "secondary":
      return a.secondary.name.localeCompare(b.secondary.name);
    case "miss_distance_km":
      return a.miss_distance_km - b.miss_distance_km;
    case "relative_velocity_km_s":
      return a.relative_velocity_km_s - b.relative_velocity_km_s;
    case "risk_score":
      return a.risk_score - b.risk_score;
    case "confidence":
      return a.confidence - b.confidence;
  }
}

export function sortEvents(events: readonly ConjunctionEvent[], sort: SortState): ConjunctionEvent[] {
  const sorted = [...events].sort((a, b) => {
    const c = compare(a, b, sort.key);
    // stable tie-break on TCA then event_id so row order never jitters
    return c !== 0 ? c : Date.parse(a.tca) - Date.parse(b.tca) || a.event_id.localeCompare(b.event_id);
  });
  return sort.dir === "asc" ? sorted : sorted.reverse();
}
