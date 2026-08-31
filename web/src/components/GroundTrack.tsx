import { useCallback, useEffect, useState } from "react";
import { api, type TrackPoint } from "../api/client";
import { WORLD_OUTLINE, type LonLat } from "../lib/worldOutline";
import "./GroundTrack.css";

/**
 * The primary's sub-satellite path on a plain equirectangular grid, with the
 * TCA position marked. The world outline is a coarse inline reference only
 * (src/lib/worldOutline.ts) — coastlines, no fills, no place labels. The
 * data is the subject; the map is a grid.
 */

const W = 360;
const H = 180;

const projX = (lon: number): number => ((lon + 180) / 360) * W;
const projY = (lat: number): number => ((90 - lat) / 180) * H;

function ringPath(ring: readonly LonLat[]): string {
  return ring
    .map(([lon, lat], i) => `${i === 0 ? "M" : "L"}${projX(lon).toFixed(1)} ${projY(lat).toFixed(1)}`)
    .join(" ");
}

/** Break the series wherever it jumps the antimeridian so no segment streaks
 * across the whole map. */
function splitAntimeridian(points: readonly TrackPoint[]): TrackPoint[][] {
  const segs: TrackPoint[][] = [];
  let current: TrackPoint[] = [];
  points.forEach((p, i) => {
    if (i > 0 && Math.abs(p.lon_deg - points[i - 1].lon_deg) > 180) {
      segs.push(current);
      current = [];
    }
    current.push(p);
  });
  if (current.length) segs.push(current);
  return segs;
}

export function GroundTrack({
  noradId,
  tcaIso,
}: {
  noradId: number;
  tcaIso: string;
}): JSX.Element {
  const [track, setTrack] = useState<TrackPoint[] | null>(null);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(() => {
    setError(null);
    setTrack(null);
    api.getObjectTrack(noradId, 24).then(setTrack).catch(setError);
  }, [noradId]);

  useEffect(load, [load]);

  const graticule: JSX.Element[] = [];
  for (let lon = -150; lon <= 150; lon += 30) {
    graticule.push(
      <line key={`v${lon}`} className="gt__grat" x1={projX(lon)} y1={0} x2={projX(lon)} y2={H} />,
    );
  }
  for (let lat = -60; lat <= 60; lat += 30) {
    graticule.push(
      <line key={`h${lat}`} className="gt__grat" x1={0} y1={projY(lat)} x2={W} y2={projY(lat)} />,
    );
  }

  let tca: TrackPoint | null = null;
  let gapMinutes = 0;
  if (track && track.length > 0) {
    const target = Date.parse(tcaIso);
    tca = track.reduce((best, p) =>
      Math.abs(Date.parse(p.t) - target) < Math.abs(Date.parse(best.t) - target) ? p : best,
    );
    gapMinutes = Math.abs(Date.parse(tca.t) - target) / 60_000;
  }

  const caption = error
    ? "ground track unavailable"
    : !track
      ? "loading ground track…"
      : track.length === 0
        ? "no ground track for this object"
        : `${gapMinutes > 60 ? "nearest available sample to TCA" : "sub-satellite point at TCA"} marked; path spans 24 h`;

  return (
    <figure className="gt">
      <svg
        className="gt__svg"
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={`Ground track of the primary object, NORAD ${noradId}, over 24 hours, with the sub-satellite point at closest approach marked.`}
      >
        <rect className="gt__frame" x={0.5} y={0.5} width={W - 1} height={H - 1} />
        {graticule}
        {WORLD_OUTLINE.map((ring, i) => (
          <path key={`coast${i}`} className="gt__coast" d={ringPath(ring)} />
        ))}
        {track &&
          splitAntimeridian(track).map((seg, i) => (
            <polyline
              key={`seg${i}`}
              className="gt__track"
              points={seg
                .map((p) => `${projX(p.lon_deg).toFixed(1)},${projY(p.lat_deg).toFixed(1)}`)
                .join(" ")}
            />
          ))}
        {tca && (
          <g className="gt__tca" transform={`translate(${projX(tca.lon_deg)} ${projY(tca.lat_deg)})`}>
            <circle className="gt__tcaring" r={6} />
            <circle className="gt__tcadot" r={3} />
          </g>
        )}
      </svg>
      <figcaption className="gt__caption">{caption}</figcaption>
    </figure>
  );
}
