import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, type TrackPoint } from "../api/client";

/**
 * Owner: visualisation role (docs/team/04-visualisation.md).
 * TODO(visualisation): render ground track / orbit path (Plotly or Cesium),
 * this is a placeholder list proving the typed client + mock track endpoint.
 */
export function OrbitView(): JSX.Element {
  const { noradId } = useParams<{ noradId: string }>();
  const [track, setTrack] = useState<TrackPoint[]>([]);
  const [error, setError] = useState<string | null>(null);

  const targetNoradId = noradId ? Number(noradId) : 25544; // ISS default

  useEffect(() => {
    api
      .getObjectTrack(targetNoradId, 6)
      .then(setTrack)
      .catch((err: Error) => setError(err.message));
  }, [targetNoradId]);

  if (error) return <p role="alert">Failed to load: {error}</p>;

  return (
    <section>
      <h1>Ground track — NORAD {targetNoradId}</h1>
      {/* TODO(visualisation): map/globe rendering instead of a raw table */}
      <table>
        <thead>
          <tr>
            <th>t</th>
            <th>lat (deg)</th>
            <th>lon (deg)</th>
            <th>alt (km)</th>
          </tr>
        </thead>
        <tbody>
          {track.map((p) => (
            <tr key={p.t}>
              <td>{p.t}</td>
              <td>{p.lat_deg.toFixed(2)}</td>
              <td>{p.lon_deg.toFixed(2)}</td>
              <td>{p.alt_km.toFixed(1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
