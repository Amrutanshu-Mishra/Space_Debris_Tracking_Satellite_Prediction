/**
 * Typed fetch client over the frozen API surface (see root README's API
 * surface list). One function per endpoint, all returning contract types
 * from src/api/types/ — never a hand-shaped inline object.
 *
 * No build-time configuration. The app and the API are always served from the
 * same origin — nginx proxies /api/ to the api service in production, and
 * Vite's dev server proxies it in `npm run dev` (see vite.config.ts) — so a
 * fixed relative base works in every deployment with nothing to set.
 *
 * The one exception is a fully static export (`npm run build:static`), which
 * drops the events fixture at /data/conjunctions.json and no API is present.
 * That is detected at runtime by probing for the file, so a single build
 * serves both modes.
 */

import type { CatalogObject } from "./types/object";
import type { ConjunctionEvent } from "./types/conjunction";
import type { CatalogStatus } from "./types/catalog_status";

/** Same-origin API mount. Relative on purpose — see file header. */
const BASE_PATH = "/api/v1";

/** Where `build:static` writes the bundled events array. */
const STATIC_DATA_URL = "/data/conjunctions.json";

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface TrackPoint {
  t: string;
  lat_deg: number;
  lon_deg: number;
  alt_km: number;
}

export interface GeometrySample {
  t: string;
  separation_km: number;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Thrown when a view needs the live API but the app is a static export. */
export class StaticModeError extends Error {
  constructor(what: string) {
    super(`${what} is not available in the static export — it needs the running API.`);
    this.name = "StaticModeError";
  }
}

// --- static-export detection (runtime, cached) ------------------------------

let staticEventsPromise: Promise<ConjunctionEvent[] | null> | null = null;

/** Fetch and cache the bundled events array, or null if there is no static
 *  export (the normal case — the file 404s and we use the API). */
function loadStaticEvents(): Promise<ConjunctionEvent[] | null> {
  if (staticEventsPromise === null) {
    staticEventsPromise = fetch(STATIC_DATA_URL)
      .then((res) => (res.ok ? (res.json() as Promise<ConjunctionEvent[]>) : null))
      .catch(() => null);
  }
  return staticEventsPromise;
}

export function isStaticMode(): Promise<boolean> {
  return loadStaticEvents().then((events) => events !== null);
}

// --- live requests --------------------------------------------------------

async function request<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  const url = new URL(`${BASE_PATH}${path}`, window.location.origin);
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined) query.set(key, String(value));
    }
  }
  const qs = query.toString();
  const url = `${BASE_URL}${path}${qs ? `?${qs}` : ""}`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new ApiError(res.status, `${res.status} ${res.statusText} for ${path}`);
  }
  return (await res.json()) as T;
}

// --- static fallbacks for the conjunction endpoints ----------------------

function paginate<T>(items: T[], limit: number, offset: number): Page<T> {
  return { items: items.slice(offset, offset + limit), total: items.length, limit, offset };
}

function filterStaticConjunctions(
  events: ConjunctionEvent[],
  opts: { tier?: string; since?: string; until?: string; min_score?: number },
): ConjunctionEvent[] {
  return events.filter((e) => {
    if (opts.tier && e.risk_tier !== opts.tier) return false;
    if (opts.since && e.tca < opts.since) return false;
    if (opts.until && e.tca > opts.until) return false;
    if (opts.min_score !== undefined && e.risk_score < opts.min_score) return false;
    return true;
  });
}

export const api = {
  health: (): Promise<{ status: string; data_source: string }> => request("/health"),

  catalogStatus: (): Promise<CatalogStatus> => request("/catalog/status"),

  listObjects: (opts: { q?: string; type?: string; limit?: number; offset?: number } = {}): Promise<
    Page<CatalogObject>
  > => request("/objects", opts),

  getObject: (noradId: number): Promise<CatalogObject> => request(`/objects/${noradId}`),

  getObjectTrack: (noradId: number, hours = 24): Promise<TrackPoint[]> =>
    request(`/objects/${noradId}/track`, { hours }),

  listConjunctions: async (
    opts: { tier?: string; since?: string; until?: string; min_score?: number; limit?: number; offset?: number } = {},
  ): Promise<Page<ConjunctionEvent>> => {
    const events = await loadStaticEvents();
    if (events) {
      const filtered = filterStaticConjunctions(events, opts);
      return paginate(filtered, opts.limit ?? 50, opts.offset ?? 0);
    }
    return request("/conjunctions", opts);
  },

  getConjunction: async (eventId: string): Promise<ConjunctionEvent> => {
    const events = await loadStaticEvents();
    if (events) {
      const found = events.find((e) => e.event_id === eventId);
      if (!found) throw new ApiError(404, `no conjunction ${eventId} in the static export`);
      return found;
    }
    return request(`/conjunctions/${eventId}`);
  },

  getConjunctionGeometry: async (eventId: string): Promise<GeometrySample[]> => {
    if (await isStaticMode()) throw new StaticModeError("Close-approach geometry");
    return request(`/conjunctions/${eventId}/geometry`);
  },
};

export type StreamMessage =
  | { type: "snapshot"; data: ConjunctionEvent[] }
  | { type: "event"; data: ConjunctionEvent };

/** Same-origin websocket to the API's /stream, protocol matched to the page. */
function streamUrl(): string {
  const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${window.location.host}${BASE_PATH}/stream`;
}

export function openEventStream(onMessage: (msg: StreamMessage) => void): WebSocket {
  const ws = new WebSocket(streamUrl());
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data) as StreamMessage;
    onMessage(msg);
  };
  return ws;
}
