import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { ConjunctionEvent } from "../api/types";
import {
  applyFilters,
  parseQuery,
  sortEvents,
  toggleSort,
  writeQuery,
  type Filters,
  type SortKey,
} from "../lib/query";
import { EventTable } from "../components/EventTable";
import { FilterBar } from "../components/FilterBar";
import { CatalogStatus } from "../components/CatalogStatus";
import { EmptyState, ErrorState, LoadingState } from "../components/AsyncState";
import "./EventList.css";

/** A slowly-ticking clock so relative times stay honest without re-rendering
 * the table every frame. */
function useNow(intervalMs = 30_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}

export function EventList(): JSX.Element {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const now = useNow();

  const { sort, filters } = useMemo(() => parseQuery(params), [params]);

  const [all, setAll] = useState<ConjunctionEvent[] | null>(null);
  // Total events in the screening run (page.total), which can exceed the
  // number fetched/displayed — the header reports this as "screened".
  const [screenedCount, setScreenedCount] = useState(0);
  const [error, setError] = useState<unknown>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Same-constellation exclusion is a fetch parameter, not a client-side
  // filter (applyFilters), so the fetched page is already the right set even
  // when it exceeds the 500-row limit. Flipping the toggle re-fetches.
  const showIntra = filters.showIntraConstellation;
  const load = useCallback(() => {
    setError(null);
    setAll(null);
    setScreenedCount(0);
    api
      .listConjunctions({ limit: 500, exclude_intra_constellation: !showIntra })
      .then((page) => {
        setAll(page.items);
        setScreenedCount(page.total);
      })
      .catch(setError);
  }, [showIntra]);

  useEffect(load, [load]);

  const rows = useMemo(
    () => (all ? sortEvents(applyFilters(all, filters, now), sort) : []),
    [all, filters, sort, now],
  );

  // drop a selection that a filter/sort change has removed from view
  useEffect(() => {
    if (selectedId && !rows.some((r) => r.event_id === selectedId)) {
      setSelectedId(null);
    }
  }, [rows, selectedId]);

  const onSort = useCallback(
    (key: SortKey) => setParams((prev) => writeQuery(prev, { sort: toggleSort(parseQuery(prev).sort, key) }), { replace: true }),
    [setParams],
  );

  const onFilters = useCallback(
    (next: Filters) => setParams((prev) => writeQuery(prev, { filters: next }), { replace: true }),
    [setParams],
  );

  const openEvent = useCallback((id: string) => navigate(`/events/${id}`), [navigate]);

  return (
    <section className="eventlist">
      <header className="eventlist__head">
        <h1 className="eventlist__title">Conjunctions</h1>
        <p className="eventlist__count" aria-live="polite">
          {all ? `${rows.length} shown of ${screenedCount} screened` : " "}
        </p>
        {all ? (
          <p className="eventlist__note">
            {showIntra
              ? "Including same-constellation pairs (Starlink / OneWeb / Globalstar / Iridium on both sides): geometrically real, but the operator station-keeps both objects, so they are not independent conjunction risk."
              : "Same-constellation pairs are hidden — the operator station-keeps both objects. Use the constellation-pairs toggle to include them."}
          </p>
        ) : null}
      </header>

      <FilterBar filters={filters} onChange={onFilters} />
      <CatalogStatus />

      {error ? (
        <ErrorState what="Could not load conjunctions." error={error} retry={load} />
      ) : !all ? (
        <LoadingState label="loading conjunctions…" />
      ) : all.length === 0 ? (
        <EmptyState
          title="No conjunction events in the latest screening run."
          hint="The last pass found nothing within 10 km. The next run may surface new approaches; catalogue status is shown above."
        />
      ) : rows.length === 0 ? (
        <EmptyState
          title="No events match these filters."
          hint="Widen the time window, lower the minimum risk score, or clear the tier toggles."
        />
      ) : (
        <EventTable
          events={rows}
          sort={sort}
          onSort={onSort}
          selectedId={selectedId}
          onSelect={setSelectedId}
          onOpen={openEvent}
          now={now}
        />
      )}
    </section>
  );
}
