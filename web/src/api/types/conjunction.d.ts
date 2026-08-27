/**
 * GENERATED SHAPE — mirrors contracts/schemas/conjunction.schema.json.
 * See object.d.ts header. Note: deliberately no probability_of_collision
 * field — see root README, "Why we don't publish a probability of
 * collision". Never add one here without updating the schema first.
 */

export type RiskTier = "GREEN" | "AMBER" | "RED";

export interface ObjectRef {
  norad_id: number;
  name: string;
}

export interface ConjunctionEvent {
  event_id: string;
  primary: ObjectRef;
  secondary: ObjectRef;
  /** ISO 8601 UTC — time of closest approach */
  tca: string;
  /** km */
  miss_distance_km: number;
  /** km/s */
  relative_velocity_km_s: number;
  /** km, signed, RTN radial */
  radial_km: number;
  /** km, signed, RTN in-track */
  in_track_km: number;
  /** km, signed, RTN cross-track */
  cross_track_km: number;
  /** metres */
  combined_radius_m: number;
  /** [0, 1] composite score, NOT a probability */
  risk_score: number;
  risk_tier: RiskTier;
  /** [0, 1] */
  confidence: number;
  confidence_note: string;
  /** hours */
  max_epoch_age_hours: number;
  /** ISO 8601 UTC */
  screened_at: string;
}
