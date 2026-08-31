/**
 * Typed fetch client over the frozen API surface (see root README's API
 * surface list). One function per endpoint, all returning contract types
 * from src/api/types/ — never a hand-shaped inline object.
 */

import type { CatalogObject } from "./types/object";
import type { ConjunctionEvent } from "./types/conjunction";
import type { CatalogStatus } from "./types/catalog_status";

// In production the bundle is served by nginx, which proxies /api same-origin,
// so BASE_URL is a root-relative path ("/api/v1"). In dev it's an absolute URL
// to the local api service. Request URLs are therefore built by string
// concatenation, not `new URL()` — the latter throws on a relative base.
const BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";
const WS_BASE_URL: string = import.meta.env.VITE_WS_BASE_URL ?? "ws://localhost:8000/api/v1";

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

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  const query = new URLSearchParams();
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

export const api = {
  health: (): Promise<{ status: string; data_source: string }> => request("/health"),

  catalogStatus: (): Promise<CatalogStatus> => request("/catalog/status"),

  listObjects: (opts: { q?: string; type?: string; limit?: number; offset?: number } = {}): Promise<
    Page<CatalogObject>
  > => request("/objects", opts),

  getObject: (noradId: number): Promise<CatalogObject> => request(`/objects/${noradId}`),

  getObjectTrack: (noradId: number, hours = 24): Promise<TrackPoint[]> =>
    request(`/objects/${noradId}/track`, { hours }),

  listConjunctions: (
    opts: { tier?: string; since?: string; until?: string; min_score?: number; limit?: number; offset?: number } = {},
  ): Promise<Page<ConjunctionEvent>> => request("/conjunctions", opts),

  getConjunction: (eventId: string): Promise<ConjunctionEvent> => request(`/conjunctions/${eventId}`),

  getConjunctionGeometry: (eventId: string): Promise<GeometrySample[]> =>
    request(`/conjunctions/${eventId}/geometry`),
};

export type StreamMessage =
  | { type: "snapshot"; data: ConjunctionEvent[] }
  | { type: "event"; data: ConjunctionEvent };

// WS_BASE_URL is an absolute ws(s):// URL in dev and a root-relative path in
// production; in the latter case resolve it against the current origin and map
// the page scheme to ws/wss.
function wsUrl(path: string): string {
  if (/^wss?:\/\//.test(WS_BASE_URL)) return `${WS_BASE_URL}${path}`;
  const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${window.location.host}${WS_BASE_URL}${path}`;
}

export function openEventStream(onMessage: (msg: StreamMessage) => void): WebSocket {
  const ws = new WebSocket(wsUrl("/stream"));
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data) as StreamMessage;
    onMessage(msg);
  };
  return ws;
}
