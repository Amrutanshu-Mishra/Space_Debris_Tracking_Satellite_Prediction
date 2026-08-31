import type { RiskTier } from "../api/types";
import "./EncounterPlane.css";

/**
 * The encounter plane — the one loud element of the detail view.
 *
 * A 2-D view of the close approach in the primary's RIC frame
 * (services/orbital/prahari_orbital/frames.py): the plane spanned by the
 * radial (R, zenith-positive) and cross-track (N) axes. In-track (T) — the
 * axis nearest the relative-velocity direction — is shown out of plane, as in
 * operational conjunction assessment.
 *
 * The radial scale is LOGARITHMIC so the hard-body keep-out circle stays
 * visible whether the miss is 100 m or 15 km; bearing from the primary is
 * drawn true. Decade rings are labelled.
 */

const SIZE = 360;
const CENTRE = SIZE / 2;
const R_PX = 150; // pixels from centre to the outer (rMax) ring

const TIER_SLUG: Record<RiskTier, "clear" | "caution" | "act"> = {
  GREEN: "clear",
  AMBER: "caution",
  RED: "act",
};

export interface EncounterPlaneProps {
  tier: RiskTier;
  radialKm: number;
  inTrackKm: number;
  crossTrackKm: number;
  missDistanceKm: number;
  combinedRadiusM: number;
}

function ringLabel(km: number): string {
  if (km >= 1) return `${km}`;
  if (km >= 0.001) return km.toFixed(km < 0.01 ? 3 : 2);
  return km.toExponential(0);
}

export function EncounterPlane({
  tier,
  radialKm,
  inTrackKm,
  crossTrackKm,
  missDistanceKm,
  combinedRadiusM,
}: EncounterPlaneProps): JSX.Element {
  const rHbKm = combinedRadiusM / 1000;
  const inPlaneKm = Math.hypot(crossTrackKm, radialKm);

  // logarithmic radial mapping: [rMin, rMax] -> [0, R_PX]
  const rMin = Math.max(rHbKm / 3, 1e-4);
  const rMax = Math.max(inPlaneKm, 10) * 1.15;
  const l0 = Math.log10(rMin);
  const l1 = Math.log10(rMax);
  const screenR = (km: number): number =>
    km <= rMin ? 0 : (R_PX * (Math.log10(km) - l0)) / (l1 - l0);

  // decade rings within range, plus the keep-out and miss radii
  const decades: number[] = [];
  for (let p = Math.ceil(l0); p <= Math.floor(l1); p += 1) decades.push(10 ** p);

  const ang = inPlaneKm === 0 ? 0 : Math.atan2(radialKm, crossTrackKm);
  const pr = screenR(inPlaneKm);
  const px = CENTRE + pr * Math.cos(ang);
  const py = CENTRE - pr * Math.sin(ang); // SVG y is down

  const keepoutR = screenR(rHbKm);
  const aheadBehind = inTrackKm >= 0 ? "ahead of" : "behind";

  return (
    <figure className="ep" data-tier={TIER_SLUG[tier]}>
      <svg
        className="ep__svg"
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        role="img"
        aria-label={
          `Encounter plane. Secondary is ${inPlaneKm.toFixed(3)} km from the primary in the ` +
          `radial/cross-track plane, ${Math.abs(inTrackKm).toFixed(3)} km ${aheadBehind} it in-track. ` +
          `Hard-body keep-out radius ${combinedRadiusM.toFixed(1)} m. Total miss ${missDistanceKm.toFixed(3)} km.`
        }
      >
        {/* decade rings */}
        {decades.map((km) => (
          <g key={`ring-${km}`}>
            <circle className="ep__ring" cx={CENTRE} cy={CENTRE} r={screenR(km)} />
            <text className="ep__ringlabel" x={CENTRE + screenR(km) + 3} y={CENTRE - 3}>
              {ringLabel(km)}
            </text>
          </g>
        ))}
        <text className="ep__ringunit" x={CENTRE + R_PX + 3} y={CENTRE + 12}>
          km
        </text>

        {/* axes */}
        <line className="ep__axis" x1={CENTRE - R_PX} y1={CENTRE} x2={CENTRE + R_PX} y2={CENTRE} />
        <line className="ep__axis" x1={CENTRE} y1={CENTRE - R_PX} x2={CENTRE} y2={CENTRE + R_PX} />
        <text className="ep__axislabel" x={CENTRE + R_PX} y={CENTRE + 16} textAnchor="end">
          cross-track  N
        </text>
        <text className="ep__axislabel" x={CENTRE + 6} y={CENTRE - R_PX + 2}>
          radial  R
        </text>

        {/* hard-body keep-out zone */}
        <circle className="ep__keepout" cx={CENTRE} cy={CENTRE} r={Math.max(keepoutR, 1.5)} />
        <line
          className="ep__leader"
          x1={CENTRE}
          y1={CENTRE}
          x2={CENTRE + Math.max(keepoutR, 1.5) + 22}
          y2={CENTRE + Math.max(keepoutR, 1.5) + 22}
        />
        <text
          className="ep__keepoutlabel"
          x={CENTRE + Math.max(keepoutR, 1.5) + 25}
          y={CENTRE + Math.max(keepoutR, 1.5) + 25}
        >
          hard-body keep-out, r = {combinedRadiusM.toFixed(1)} m
        </text>

        {/* miss vector + secondary position */}
        {inPlaneKm > 0 && (
          <>
            <line className="ep__miss" x1={CENTRE} y1={CENTRE} x2={px} y2={py} />
            <text
              className="ep__misslabel"
              x={(CENTRE + px) / 2 + 6}
              y={(CENTRE + py) / 2 - 4}
            >
              {inPlaneKm.toFixed(3)} km in-plane
            </text>
          </>
        )}
        <circle className="ep__primary" cx={CENTRE} cy={CENTRE} r={2.5} />
        <circle className="ep__secondary" cx={px} cy={py} r={4} />
        <text className="ep__secondarylabel" x={px + 8} y={py + 4}>
          secondary at TCA
        </text>
      </svg>

      <figcaption className="ep__caption">
        <p className="ep__scale">
          Radial scale is logarithmic — rings mark decades; bearing from the primary is true.
          In-track is out of plane.
        </p>
        <dl className="ep__oop">
          <div>
            <dt>total miss</dt>
            <dd>{missDistanceKm.toFixed(3)} km</dd>
          </div>
          <div>
            <dt>in-track (out of plane)</dt>
            <dd>
              {Math.abs(inTrackKm).toFixed(3)} km {aheadBehind} primary
            </dd>
          </div>
        </dl>
      </figcaption>
    </figure>
  );
}
