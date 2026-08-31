import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { CatalogStatus as CatalogStatusData } from "../api/types";
import { formatCount, hours } from "../lib/format";
import { Timestamp } from "./Timestamp";
import { ErrorState, LoadingState } from "./AsyncState";
import "./CatalogStatus.css";

const STALE_HOURS = 168; // one week — matches prahari_orbital.scoring confidence decay

/**
 * Compact catalogue-health strip for the list view: object count, last
 * refresh, screening window, and — with visual weight, because it is part of
 * the trust argument, not decoration — the age of the underlying TLEs.
 */
export function CatalogStatus(): JSX.Element {
  const [status, setStatus] = useState<CatalogStatusData | null>(null);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(() => {
    setError(null);
    setStatus(null);
    api.catalogStatus().then(setStatus).catch(setError);
  }, []);

  useEffect(load, [load]);

  if (error) {
    return <ErrorState what="Catalogue status is unavailable." error={error} retry={load} />;
  }
  if (!status) {
    return <LoadingState label="loading catalogue status…" />;
  }

  const age = status.epoch_age_hours;
  const stale = age.max >= STALE_HOURS;

  return (
    <dl className="catstatus">
      <div className="catstatus__item">
        <dt className="catstatus__label">objects tracked</dt>
        <dd className="catstatus__value">{formatCount(status.object_count)}</dd>
      </div>

      <div className="catstatus__item">
        <dt className="catstatus__label">catalogue refreshed</dt>
        <dd className="catstatus__value">
          <Timestamp iso={status.last_refresh} />
        </dd>
      </div>

      <div className="catstatus__item">
        <dt className="catstatus__label">screening window</dt>
        <dd className="catstatus__value">{hours(status.screening_window_hours)}</dd>
      </div>

      <div className="catstatus__item catstatus__item--age" data-stale={stale || undefined}>
        <dt className="catstatus__label">oldest TLE in catalogue</dt>
        <dd className="catstatus__value">{hours(age.max)}</dd>
        <dd className="catstatus__note">
          <span>median {hours(age.p50)}</span>
          <span>90th percentile {hours(age.p90)}</span>
          <span>treated as stale past {hours(STALE_HOURS)}</span>
        </dd>
      </div>
    </dl>
  );
}
