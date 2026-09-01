import type { ReactNode } from "react";
import { ApiError, StaticModeError } from "../api/client";

/**
 * Loading / empty / error as real components, per the frontend brief:
 * an empty result says what to change; an error says what failed and what
 * to do about it. No bare spinners, no blank divs.
 */

export function LoadingState({ label }: { label: string }): JSX.Element {
  return (
    <div className="state state--loading" role="status" aria-live="polite">
      <span className="state__mono">{label}</span>
    </div>
  );
}

export function EmptyState({ title, hint }: { title: string; hint: ReactNode }): JSX.Element {
  return (
    <div className="state state--empty">
      <p className="state__title">{title}</p>
      <p className="state__hint">{hint}</p>
    </div>
  );
}

function errorHint(error: unknown): ReactNode {
  if (error instanceof StaticModeError) {
    return (
      <>
        This page is running from a static export (<code>npm run build:static</code>), which
        bundles the screened-events file but has no API behind it. Views that need live
        propagation — geometry, ground tracks, catalogue search — only work against a
        running backend.
      </>
    );
  }
  if (error instanceof ApiError && error.status >= 500) {
    return (
      <>
        The API returned <code>{error.status}</code>. Check its logs (
        <code>docker compose logs api</code>) — it logs at startup which data source and
        cache it chose, so a mode mismatch shows there.
      </>
    );
  }
  if (error instanceof ApiError && error.status === 404) {
    return <>The API is up but has no record for this request.</>;
  }
  // Network / CORS / proxy failure — the request never got a response.
  return (
    <>
      The request to <code>/api/v1</code> did not get a response. Check the API container is
      running and healthy (<code>curl -s localhost:8000/api/v1/health</code> should return{" "}
      <code>{`{"status":"ok"}`}</code>) and that whatever serves this page forwards{" "}
      <code>/api/</code> to it.
    </>
  );
}

export function ErrorState({
  what,
  error,
  retry,
}: {
  what: string;
  error: unknown;
  retry?: () => void;
}): JSX.Element {
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div className="state state--error" role="alert">
      <p className="state__title">{what}</p>
      <p className="state__mono">{message}</p>
      <p className="state__hint">{errorHint(error)}</p>
      {retry ? (
        <button type="button" className="state__retry" onClick={retry}>
          retry
        </button>
      ) : null}
    </div>
  );
}
