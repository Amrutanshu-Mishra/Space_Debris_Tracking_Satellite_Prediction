import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { ConjunctionEvent } from "../api/types";
import { EncounterPlane } from "../components/EncounterPlane";
import { GroundTrack } from "../components/GroundTrack";
import { ConfidencePanel } from "../components/ConfidencePanel";
import { Timestamp } from "../components/Timestamp";
import { EmptyState, ErrorState, LoadingState } from "../components/AsyncState";
import { relativeToTca } from "../lib/format";
import "./EventDetail.css";

function isNotFound(err: unknown): boolean {
  return err instanceof Error && /\b404\b/.test(err.message);
}

export function EventDetail(): JSX.Element {
  const { eventId } = useParams<{ eventId: string }>();
  const [event, setEvent] = useState<ConjunctionEvent | null>(null);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(() => {
    if (!eventId) return;
    setError(null);
    setEvent(null);
    api.getConjunction(eventId).then(setEvent).catch(setError);
  }, [eventId]);

  useEffect(load, [load]);

  return (
    <section className="detail">
      <p className="detail__crumb">
        <Link to="/">back to screening</Link>
      </p>

      {error ? (
        isNotFound(error) ? (
          <EmptyState
            title="This event is not in the current screening run."
            hint={<Link to="/">Return to the conjunction list.</Link>}
          />
        ) : (
          <ErrorState what="Could not load this event." error={error} retry={load} />
        )
      ) : !event ? (
        <LoadingState label="loading event…" />
      ) : (
        <Loaded event={event} />
      )}
    </section>
  );
}

function Loaded({ event: e }: { event: ConjunctionEvent }): JSX.Element {
  return (
    <>
      <header className="detail__head">
        <h1 className="detail__title">
          {e.primary.name} <span className="detail__x">×</span> {e.secondary.name}
        </h1>
        <p className="detail__id">{e.event_id}</p>
      </header>

      <div className="detail__plane">
        <EncounterPlane
          tier={e.risk_tier}
          radialKm={e.radial_km}
          inTrackKm={e.in_track_km}
          crossTrackKm={e.cross_track_km}
          missDistanceKm={e.miss_distance_km}
          combinedRadiusM={e.combined_radius_m}
        />
      </div>

      <div className="detail__grid">
        <dl className="detail__facts">
          <div>
            <dt>primary</dt>
            <dd>
              <Link to={`/orbit/${e.primary.norad_id}`}>{e.primary.name}</Link>{" "}
              <span className="detail__norad">{e.primary.norad_id}</span>
            </dd>
          </div>
          <div>
            <dt>secondary</dt>
            <dd>
              <Link to={`/orbit/${e.secondary.norad_id}`}>{e.secondary.name}</Link>{" "}
              <span className="detail__norad">{e.secondary.norad_id}</span>
            </dd>
          </div>
          <div>
            <dt>TCA</dt>
            <dd>
              <Timestamp iso={e.tca} /> <span className="detail__rel">{relativeToTca(e.tca)}</span>
            </dd>
          </div>
          <div>
            <dt>miss distance</dt>
            <dd className="num">{e.miss_distance_km.toFixed(3)} km</dd>
          </div>
          <div>
            <dt>relative velocity</dt>
            <dd className="num">{e.relative_velocity_km_s.toFixed(2)} km/s</dd>
          </div>
          <div>
            <dt>combined hard-body radius</dt>
            <dd className="num">{e.combined_radius_m.toFixed(1)} m</dd>
          </div>
          <div>
            <dt>radial (R)</dt>
            <dd className="num">{e.radial_km.toFixed(3)} km</dd>
          </div>
          <div>
            <dt>in-track (T)</dt>
            <dd className="num">{e.in_track_km.toFixed(3)} km</dd>
          </div>
          <div>
            <dt>cross-track (N)</dt>
            <dd className="num">{e.cross_track_km.toFixed(3)} km</dd>
          </div>
          <div>
            <dt>risk score</dt>
            <dd className="num">
              {e.risk_score.toFixed(2)} <span className="detail__tier">{e.risk_tier}</span>
            </dd>
          </div>
          <div>
            <dt>screened</dt>
            <dd>
              <Timestamp iso={e.screened_at} />
            </dd>
          </div>
        </dl>

        <GroundTrack noradId={e.primary.norad_id} tcaIso={e.tca} />
      </div>

      <ConfidencePanel
        confidence={e.confidence}
        confidenceNote={e.confidence_note}
        maxEpochAgeHours={e.max_epoch_age_hours}
      />
    </>
  );
}
