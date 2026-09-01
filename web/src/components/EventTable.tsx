import { useEffect, useRef, type KeyboardEvent } from "react";
import type { ConjunctionEvent } from "../api/types";
import type { SortKey, SortState } from "../lib/query";
import { absoluteUtc, relativeToTca } from "../lib/format";
import { RiskIndicator } from "./RiskIndicator";
import "./EventTable.css";

interface Column {
  key: SortKey;
  label: string;
  unit?: string;
  num?: boolean;
}

const COLUMNS: readonly Column[] = [
  { key: "tca", label: "time to TCA" },
  { key: "primary", label: "primary" },
  { key: "secondary", label: "secondary" },
  { key: "miss_distance_km", label: "miss", unit: "km", num: true },
  { key: "relative_velocity_km_s", label: "rel vel", unit: "km/s", num: true },
  { key: "risk_score", label: "risk", num: true },
  { key: "confidence", label: "confidence", num: true },
];

const TIER_SLUG = { GREEN: "clear", AMBER: "caution", RED: "act" } as const;

export interface EventTableProps {
  events: readonly ConjunctionEvent[];
  sort: SortState;
  onSort: (key: SortKey) => void;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onOpen: (id: string) => void;
  /** Clock for relative times; passed in so every row agrees. */
  now: number;
}

export function EventTable({
  events,
  sort,
  onSort,
  selectedId,
  onSelect,
  onOpen,
  now,
}: EventTableProps): JSX.Element {
  const gridRef = useRef<HTMLDivElement>(null);

  // keep the selected row in view as the selection moves by keyboard
  useEffect(() => {
    if (!selectedId) return;
    document.getElementById(`evt-${selectedId}`)?.scrollIntoView({ block: "nearest" });
  }, [selectedId]);

  function moveSelection(delta: number): void {
    if (events.length === 0) return;
    const current = events.findIndex((e) => e.event_id === selectedId);
    const next =
      current < 0
        ? delta > 0
          ? 0
          : events.length - 1
        : Math.min(events.length - 1, Math.max(0, current + delta));
    onSelect(events[next].event_id);
  }

  function onKeyDown(ev: KeyboardEvent<HTMLDivElement>): void {
    switch (ev.key) {
      case "ArrowDown":
        ev.preventDefault();
        moveSelection(1);
        break;
      case "ArrowUp":
        ev.preventDefault();
        moveSelection(-1);
        break;
      case "Home":
        ev.preventDefault();
        if (events.length) onSelect(events[0].event_id);
        break;
      case "End":
        ev.preventDefault();
        if (events.length) onSelect(events[events.length - 1].event_id);
        break;
      case "Enter":
        if (selectedId) {
          ev.preventDefault();
          onOpen(selectedId);
        }
        break;
    }
  }

  return (
    <div
      ref={gridRef}
      className="etable"
      role="grid"
      tabIndex={0}
      aria-label="Upcoming conjunctions. Arrow keys move the selection, Enter opens the event."
      aria-activedescendant={selectedId ? `evt-${selectedId}` : undefined}
      onKeyDown={onKeyDown}
    >
      <table>
        <thead>
          <tr role="row">
            {COLUMNS.map((col) => {
              const active = sort.key === col.key;
              return (
                <th
                  key={col.key}
                  scope="col"
                  className={col.num ? "num" : undefined}
                  data-active={active || undefined}
                  aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}
                >
                  <button type="button" className="etable__sort" onClick={() => onSort(col.key)}>
                    <span className="etable__collabel">{col.label}</span>
                    {col.unit ? <span className="etable__unit">{col.unit}</span> : null}
                    <span className="etable__arrow" aria-hidden="true">
                      {active ? (sort.dir === "asc" ? "▲" : "▼") : ""}
                    </span>
                  </button>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {events.map((e) => {
            const selected = e.event_id === selectedId;
            const low = e.confidence < 0.4;
            return (
              <tr
                key={e.event_id}
                id={`evt-${e.event_id}`}
                role="row"
                aria-selected={selected}
                data-selected={selected || undefined}
                data-intra={e.intra_constellation || undefined}
                onClick={() => onSelect(e.event_id)}
                onDoubleClick={() => onOpen(e.event_id)}
              >
                <td>
                  <a
                    className="etable__open"
                    href={`/events/${e.event_id}`}
                    title={absoluteUtc(e.tca)}
                    onClick={(ev) => {
                      ev.preventDefault();
                      ev.stopPropagation();
                      onSelect(e.event_id);
                      onOpen(e.event_id);
                    }}
                  >
                    {relativeToTca(e.tca, now)}
                  </a>
                </td>
                <td>
                  <span className="obj__name">{e.primary.name}</span>
                  <span className="obj__id">{e.primary.norad_id}</span>
                </td>
                <td>
                  <span className="obj__name">{e.secondary.name}</span>
                  <span className="obj__id">{e.secondary.norad_id}</span>
                  {e.intra_constellation ? (
                    <span
                      className="obj__intra"
                      title="Both objects are the same station-kept constellation — an operator-managed pair, not independent conjunction risk. Shown because the constellation-pairs filter is on."
                    >
                      same constellation
                    </span>
                  ) : null}
                </td>
                <td className="num">{e.miss_distance_km.toFixed(3)}</td>
                <td className="num">{e.relative_velocity_km_s.toFixed(2)}</td>
                <td className="num cell-risk" data-tier={TIER_SLUG[e.risk_tier]}>
                  <RiskIndicator tier={e.risk_tier} score={e.risk_score} confidence={e.confidence} />
                </td>
                <td className="num cell-conf" data-band={low ? "low" : undefined}>
                  <span className="cell-conf__val">{e.confidence.toFixed(2)}</span>
                  <span className="cell-conf__age" title="age of the older of the two TLE epochs">
                    TLE {Math.round(e.max_epoch_age_hours)} h
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
