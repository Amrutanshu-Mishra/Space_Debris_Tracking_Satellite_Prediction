import type { RiskTier } from "../api/types";
import "./RiskIndicator.css";

/**
 * The signature element at row scale (DESIGN.md §4).
 *
 * Risk and confidence are shown as ONE mark, not two badges: a gauge whose
 * colour is the risk tier, whose fill *height* is the confidence, and whose
 * fill *texture* is the confidence band (solid / fine hatch / coarse hatch).
 * You cannot read the tier colour without also seeing how full — how much the
 * data is trusted — the mark is. The numeric `risk_score` and `confidence`
 * sit in a readout bound to that gauge.
 *
 * A stale RED and a fresh RED are the same colour at different fill levels —
 * the distinction a one-axis severity badge throws away.
 */

type Band = "high" | "reduced" | "low";

function bandOf(confidence: number): Band {
  if (confidence >= 0.7) return "high";
  if (confidence >= 0.4) return "reduced";
  return "low";
}

const TIER_SLUG: Record<RiskTier, "clear" | "caution" | "act"> = {
  GREEN: "clear",
  AMBER: "caution",
  RED: "act",
};

const BAND_PHRASE: Record<Band, string> = {
  high: "fresh data",
  reduced: "reduced — data ageing",
  low: "low — data stale",
};

export function RiskIndicator({
  tier,
  score,
  confidence,
}: {
  tier: RiskTier;
  score: number;
  confidence: number;
}): JSX.Element {
  const band = bandOf(confidence);
  const fillPct = Math.max(4, Math.min(100, Math.round(confidence * 100)));
  const label = `${tier} risk, score ${score.toFixed(2)}; confidence ${confidence.toFixed(
    2,
  )} (${BAND_PHRASE[band]})`;

  return (
    <span className="ri" data-tier={TIER_SLUG[tier]} data-band={band} role="img" aria-label={label}>
      <span className="ri__gauge" aria-hidden="true">
        <span className="ri__fill" style={{ height: `${fillPct}%` }} />
      </span>
      <span className="ri__read" aria-hidden="true">
        <span className="ri__score">{score.toFixed(2)}</span>
        <span className="ri__conf">
          <span className="ri__letter">{tier[0]}</span>
          <span className="ri__cval">c{confidence.toFixed(2)}</span>
          {band === "low" ? <span className="ri__warn"> ⚠</span> : null}
        </span>
      </span>
    </span>
  );
}
