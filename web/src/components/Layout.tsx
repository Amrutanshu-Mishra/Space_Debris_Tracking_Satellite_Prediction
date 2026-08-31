import { useEffect, useState, type ReactNode } from "react";
import { api } from "../api/client";
import type { CatalogStatus } from "../api/types";
import { formatCount } from "../lib/format";
import { Timestamp } from "./Timestamp";

/**
 * The console frame from DESIGN.md §3: a fixed masthead — product mark, the
 * mock/live data-source tag, the catalogue refresh time, and the screening
 * funnel as labelled figures on a hairline-ruled row (no arrows, no middle
 * dots) — above a full-width content region.
 *
 * AppHeader fetches its own catalogue status and degrades quietly: if the
 * API is unreachable the mark and tag still render, the funnel just omits.
 */

export function AppHeader(): JSX.Element {
  const [status, setStatus] = useState<CatalogStatus | null>(null);
  const [source, setSource] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api
      .catalogStatus()
      .then((s) => live && setStatus(s))
      .catch(() => undefined);
    api
      .health()
      .then((h) => live && setSource(h.data_source))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);

  return (
    <header className="masthead">
      <div className="masthead__row">
        <span className="masthead__brand">PRAHARI</span>
        {source ? (
          <span className="tag" data-source={source}>
            {source}
          </span>
        ) : null}
        {status ? (
          <span className="masthead__refresh">
            catalogue refreshed <Timestamp iso={status.last_refresh} />
          </span>
        ) : null}
      </div>

      {status ? (
        <div className="funnel">
          <div className="funnel__cell">
            <span className="funnel__label">pairs considered</span>
            <span className="funnel__value">{formatCount(status.pairs_considered)}</span>
          </div>
          <div className="funnel__cell">
            <span className="funnel__label">pairs fine-screened</span>
            <span className="funnel__value">{formatCount(status.pairs_fine_screened)}</span>
          </div>
          <div className="funnel__cell">
            <span className="funnel__label">events found</span>
            <span className="funnel__value">{formatCount(status.events_found)}</span>
          </div>
          <div className="funnel__cell">
            <span className="funnel__label">screening window</span>
            <span className="funnel__value">{status.screening_window_hours} h</span>
          </div>
        </div>
      ) : null}
    </header>
  );
}

export function Layout({ children }: { children: ReactNode }): JSX.Element {
  return (
    <div className="app">
      <AppHeader />
      <main className="app__content" id="main-content">
        {children}
      </main>
    </div>
  );
}
