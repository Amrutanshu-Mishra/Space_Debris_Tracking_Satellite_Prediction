/**
 * Typed fetch client over the frozen API surface (see root README's API
 * surface list). One function per endpoint, all returning contract types
 * from src/api/types/ — never a hand-shaped inline object.
 *
 * There is no build-time configuration. The app and the API are always served
 * from the same origin: nginx proxies /api/ to the api service in production,
 * and the Vite dev server proxies it in `npm run dev`. So the base is the
 * fixed relative path "/api/v1" and there is nothing to set per deployment.
 *
 * The one exception is a fully static export (`npm run build:static`), which
 * writes the screened-events fixture to /data/conjunctions.json with no API
 * behind it. That is detected at runtime by probing for the file, so a single
 * code build serves both modes.
 */

import type { CatalogObject } from "./types/object";
import type { ConjunctionEvent } from "./types/conjunction";
import type { CatalogStatus } from "./types/catalog_status";

/** Same-origin API mount. Relative on purpose — see the file header. */
const BASE_PATH = "/api/v1";

/** Where `npm run build:static` drops the bundled events array. */
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

/** Thrown when a view needs the live API but this is a static export. */
export class StaticModeError extends Error {
  constructor(what: string) {
    super(`${what} needs the running API and is not available in the static export.`);
    this.name = "StaticModeError";
  }
}

type QueryParams = Record<string, string | number | undefined>;

/** "?a=1&b=2" (or "" when there is nothing to add). URLSearchParams only —
 *  the base is relative, so `new URL()` has no valid base to resolve against. */
function queryString(params?: QueryParams): string {
  if (!params) return "";
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) search.set(key, String(value));
  }
  const encoded = search.toString();
  return encoded ? `?${encoded}` : "";
}

async function request<T>(path: string, params?: QueryParams): Promise<T> {
  const res = await fetch(`${BASE_PATH}${path}${queryString(params)}`);
  if (!res.ok) {
    throw new ApiError(res.status, `${res.status} ${res.statusText} for ${BASE_PATH}${path}`);
  }
  return (await res.json()) as T;
}

// --- static export -------------------------------------------------------

let staticEventsPromise: Promise<ConjunctionEvent[] | null> | null = null;

/** The bundled events array, or null when there is no static export (the
 *  normal case: /data/conjunctions.json 404s and every call uses the API).
 *  Fetched once and cached for the page's lifetime. */
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

interface ConjunctionQuery {
  tier?: string;
  since?: string;
  until?: string;
  min_score?: number;
  limit?: number;
  offset?: number;
}

/** Filter, then sort chronologically by TCA (ISO 8601 strings sort
 *  lexicographically), matching the order a "what's coming up" list wants.
 *  Mirrors the mock data source's filters exactly. */
function selectStaticConjunctions(
  events: ConjunctionEvent[],
  opts: ConjunctionQuery,
): ConjunctionEvent[] {
  const filtered = events.filter((event) => {
    if (opts.tier && event.risk_tier !== opts.tier) return false;
    if (opts.since && event.tca < opts.since) return false;
    if (opts.until && event.tca > opts.until) return false;
    if (opts.min_score !== undefined && event.risk_score < opts.min_score) return false;
    return true;
  });
  return filtered.sort((a, b) => (a.tca < b.tca ? -1 : a.tca > b.tca ? 1 : 0));
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

  listConjunctions: async (opts: ConjunctionQuery = {}): Promise<Page<ConjunctionEvent>> => {
    const staticEvents = await loadStaticEvents();
    if (staticEvents) {
      const selected = selectStaticConjunctions(staticEvents, opts);
      const limit = opts.limit ?? 50;
      const offset = opts.offset ?? 0;
      return { items: selected.slice(offset, offset + limit), total: selected.length, limit, offset };
    }
    return request("/conjunctions", { ...opts });
  },

  getConjunction: async (eventId: string): Promise<ConjunctionEvent> => {
    const staticEvents = await loadStaticEvents();
    if (staticEvents) {
      const found = staticEvents.find((event) => event.event_id === eventId);
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

/** Same-origin websocket to the API's /stream, scheme matched to the page. */
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
