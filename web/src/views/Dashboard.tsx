import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { ConjunctionEvent } from "../api/types/conjunction";
import type { CatalogStatus } from "../api/types/catalog_status";

/**
 * Owner: dashboard role (docs/team/05-dashboard.md).
 * TODO(dashboard): event table with filters, epoch-age indicators, alert list.
 * This is a routed stub proving the typed client + mock API round-trip —
 * not the real dashboard.
 */
export function Dashboard(): JSX.Element {
  const [status, setStatus] = useState<CatalogStatus | null>(null);
  const [events, setEvents] = useState<ConjunctionEvent[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .catalogStatus()
      .then(setStatus)
      .catch((err: Error) => setError(err.message));
    api
      .listConjunctions({ limit: 20 })
      .then((page) => setEvents(page.items))
      .catch((err: Error) => setError(err.message));
  }, []);

  if (error) return <p role="alert">Failed to load: {error}</p>;

  return (
    <section>
      <h1>Catalogue status</h1>
      {status ? (
        <ul>
          <li>Objects tracked: {status.object_count}</li>
          <li>Screening window: {status.screening_window_hours} h</li>
          <li>Events found: {status.events_found}</li>
        </ul>
      ) : (
        <p>Loading catalogue status…</p>
      )}

      <h1>Recent conjunctions</h1>
      {/* TODO(dashboard): tier filter, min-score filter, sortable columns */}
      <table>
        <thead>
          <tr>
            <th>TCA</th>
            <th>Primary</th>
            <th>Secondary</th>
            <th>Miss (km)</th>
            <th>Tier</th>
            <th>Confidence</th>
          </tr>
        </thead>
        <tbody>
          {events.map((e) => (
            <tr key={e.event_id}>
              <td>{e.tca}</td>
              <td>{e.primary.name}</td>
              <td>{e.secondary.name}</td>
              <td>{e.miss_distance_km.toFixed(3)}</td>
              <td>{e.risk_tier}</td>
              <td>{e.confidence.toFixed(2)}</td>
              <td>
                <Link to={`/events/${e.event_id}`}>details</Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
