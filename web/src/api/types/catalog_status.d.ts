/**
 * GENERATED SHAPE — mirrors contracts/schemas/catalog_status.schema.json.
 * See object.d.ts header.
 */

export interface EpochAgeDistribution {
  /** hours */
  p50: number;
  /** hours */
  p90: number;
  /** hours */
  max: number;
}

export interface CatalogStatus {
  object_count: number;
  /** ISO 8601 UTC */
  last_refresh: string;
  /** ISO 8601 UTC */
  next_refresh: string;
  source: string;
  epoch_age_hours: EpochAgeDistribution;
  /** hours */
  screening_window_hours: number;
  /** seconds */
  last_screen_duration_s: number;
  pairs_considered: number;
  pairs_fine_screened: number;
  events_found: number;
}
