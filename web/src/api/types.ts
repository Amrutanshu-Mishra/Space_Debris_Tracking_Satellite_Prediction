/**
 * Barrel over the generated contract types in ./types/. Import contract
 * shapes from here (`@/api/types`) rather than reaching into the individual
 * files.
 *
 * ./types/object.d.ts, ./types/conjunction.d.ts, and ./types/catalog_status.d.ts
 * are GENERATED from contracts/schemas/*.schema.json by `npm run contracts`
 * (equivalently `make seed`). Do not hand-edit them, and do not declare a
 * shape here that is not in a schema — see contracts/README.md, "The freeze
 * rule". In particular there is no probability_of_collision field, ever.
 */

import type { CatalogObject } from "./types/object";
import type { ConjunctionEvent, ObjectRef } from "./types/conjunction";
import type { CatalogStatus } from "./types/catalog_status";

export type { CatalogObject, ConjunctionEvent, ObjectRef, CatalogStatus };

/**
 * Convenience aliases derived from the generated interfaces, so they stay
 * correct across regeneration — `json2ts` inlines these as string-literal
 * unions / inline objects rather than exporting a named type.
 */
export type RiskTier = ConjunctionEvent["risk_tier"];
export type ObjectType = CatalogObject["object_type"];
export type RcsSize = CatalogObject["rcs_size"];
export type EpochAgeDistribution = CatalogStatus["epoch_age_hours"];
