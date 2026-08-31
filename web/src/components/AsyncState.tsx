import type { ReactNode } from "react";

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

function apiBase(): string {
  return import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";
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
      <p className="state__hint">
        Check the API is reachable at <code>{apiBase()}</code> and that it started cleanly —{" "}
        <code>PRAHARI_DATA_SOURCE=mock</code> serves the fixtures with no database.
      </p>
      {retry ? (
        <button type="button" className="state__retry" onClick={retry}>
          retry
        </button>
      ) : null}
    </div>
  );
}
