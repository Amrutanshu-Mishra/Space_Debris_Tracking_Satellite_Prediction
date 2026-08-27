import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, type GeometrySample } from "../api/client";
import type { ConjunctionEvent } from "../api/types/conjunction";

/**
 * Owner: dashboard role for the layout, visualisation role for the geometry
 * chart (docs/team/04-visualisation.md, docs/team/05-dashboard.md).
 * TODO(visualisation): plot geometry samples (Plotly) around TCA.
 * TODO(dashboard): full event detail layout — RTN breakdown, epoch-age
 * badges, links back to both objects.
 */
export function EventDetail(): JSX.Element {
  const { eventId } = useParams<{ eventId: string }>();
  const [event, setEvent] = useState<ConjunctionEvent | null>(null);
  const [geometry, setGeometry] = useState<GeometrySample[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!eventId) return;
    api
      .getConjunction(eventId)
      .then(setEvent)
      .catch((err: Error) => setError(err.message));
    api
      .getConjunctionGeometry(eventId)
      .then(setGeometry)
      .catch((err: Error) => setError(err.message));
  }, [eventId]);

  if (error) return <p role="alert">Failed to load: {error}</p>;
  if (!event) return <p>Loading event…</p>;

  return (
    <section>
      <h1>
        {event.primary.name} × {event.secondary.name}
      </h1>
      <dl>
        <dt>TCA</dt>
        <dd>{event.tca}</dd>
        <dt>Miss distance</dt>
        <dd>{event.miss_distance_km.toFixed(3)} km</dd>
        <dt>Relative velocity</dt>
        <dd>{event.relative_velocity_km_s.toFixed(2)} km/s</dd>
        <dt>Risk score</dt>
        <dd>
          {event.risk_score.toFixed(2)} ({event.risk_tier})
        </dd>
        <dt>Confidence</dt>
        <dd>{event.confidence.toFixed(2)}</dd>
        <dt>Confidence note</dt>
        <dd>{event.confidence_note}</dd>
      </dl>

      {/* TODO(visualisation): real geometry plot, this is a placeholder table */}
      <h2>Geometry around TCA</h2>
      <ul>
        {geometry.map((s) => (
          <li key={s.t}>
            {s.t}: {s.separation_km.toFixed(3)} km
          </li>
        ))}
      </ul>
    </section>
  );
}
