import type { RiskTier } from "../api/types";
import {
  ALL_TIERS,
  DEFAULT_FILTERS,
  WINDOW_CHOICES,
  type Filters,
} from "../lib/query";
import "./FilterBar.css";

const TIER_SLUG: Record<RiskTier, "clear" | "caution" | "act"> = {
  GREEN: "clear",
  AMBER: "caution",
  RED: "act",
};

function windowLabel(h: number | null): string {
  if (h === null) return "any time";
  if (h % 24 === 0) return `next ${h / 24} d`;
  return `next ${h} h`;
}

function isDefault(f: Filters): boolean {
  return f.tiers.length === 0 && f.windowHours === null && f.minScore <= 0;
}

export function FilterBar({
  filters,
  onChange,
}: {
  filters: Filters;
  onChange: (next: Filters) => void;
}): JSX.Element {
  const toggleTier = (t: RiskTier): void => {
    const tiers = filters.tiers.includes(t)
      ? filters.tiers.filter((x) => x !== t)
      : [...filters.tiers, t];
    onChange({ ...filters, tiers });
  };

  const showingAll = filters.tiers.length === 0;

  return (
    <div className="filterbar" role="group" aria-label="Filter conjunctions">
      <div className="filterbar__group">
        <span className="filterbar__label" id="filter-tier">
          tier
        </span>
        <div className="filterbar__tiers" role="group" aria-labelledby="filter-tier">
          {ALL_TIERS.map((t) => {
            const on = showingAll || filters.tiers.includes(t);
            return (
              <button
                key={t}
                type="button"
                className="tiertoggle"
                data-tier={TIER_SLUG[t]}
                data-on={on || undefined}
                aria-pressed={!showingAll && filters.tiers.includes(t)}
                aria-label={t}
                title={t}
                onClick={() => toggleTier(t)}
              >
                {t[0]}
              </button>
            );
          })}
        </div>
      </div>

      <label className="filterbar__group">
        <span className="filterbar__label">time window</span>
        <select
          className="filterbar__select"
          value={filters.windowHours === null ? "all" : String(filters.windowHours)}
          onChange={(e) =>
            onChange({
              ...filters,
              windowHours: e.target.value === "all" ? null : Number(e.target.value),
            })
          }
        >
          {WINDOW_CHOICES.map((h) => (
            <option key={h === null ? "all" : h} value={h === null ? "all" : String(h)}>
              {windowLabel(h)}
            </option>
          ))}
        </select>
      </label>

      <label className="filterbar__group">
        <span className="filterbar__label">min risk score</span>
        <input
          className="filterbar__range"
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={filters.minScore}
          onChange={(e) => onChange({ ...filters, minScore: Number(e.target.value) })}
          aria-valuetext={filters.minScore.toFixed(2)}
        />
        <output className="filterbar__out">{filters.minScore.toFixed(2)}</output>
      </label>

      <button
        type="button"
        className="filterbar__clear"
        onClick={() => onChange(DEFAULT_FILTERS)}
        disabled={isDefault(filters)}
      >
        clear filters
      </button>
    </div>
  );
}
