/**
 * GENERATED SHAPE — mirrors contracts/schemas/object.schema.json.
 * Normally produced by `make seed` (json-schema-to-typescript). Hand-written
 * for the skeleton so the rest of the frontend has something to import
 * against; do not hand-edit field lists, edit the schema and regenerate.
 */

export type ObjectType = "PAYLOAD" | "ROCKET_BODY" | "DEBRIS" | "UNKNOWN";
export type RcsSize = "SMALL" | "MEDIUM" | "LARGE" | "UNKNOWN";

export interface CatalogObject {
  norad_id: number;
  name: string;
  tle_line1: string;
  tle_line2: string;
  /** ISO 8601 UTC */
  epoch: string;
  /** hours */
  epoch_age_hours: number;
  object_type: ObjectType;
  rcs_size: RcsSize;
  /** metres */
  radius_m: number;
  /** km */
  perigee_km: number;
  /** km */
  apogee_km: number;
  /** degrees */
  inclination_deg: number;
}
