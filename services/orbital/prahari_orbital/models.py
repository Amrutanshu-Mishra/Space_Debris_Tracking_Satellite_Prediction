"""Pydantic models mirroring contracts/schemas/*.schema.json.

GENERATED SHAPE — do not hand-edit the field lists. This file is normally
produced by `make seed` (datamodel-code-generator against
contracts/schemas/). It is checked in by hand for the skeleton so the rest
of the codebase has something concrete to import against; once `make seed`
is run for real it will overwrite this file with byte-identical field
definitions plus generator boilerplate.

Regenerate: contracts/README.md, "Regenerating models from schemas".
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ObjectType(str, Enum):
    PAYLOAD = "PAYLOAD"
    ROCKET_BODY = "ROCKET_BODY"
    DEBRIS = "DEBRIS"
    UNKNOWN = "UNKNOWN"


class RcsSize(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"
    UNKNOWN = "UNKNOWN"


class RiskTier(str, Enum):
    GREEN = "GREEN"
    AMBER = "AMBER"
    RED = "RED"


class CatalogObject(BaseModel):
    """A single object in the tracked catalogue, derived from a CelesTrak GP/TLE record."""

    norad_id: int = Field(..., ge=1, description="NORAD catalogue number.")
    name: str = Field(..., min_length=1)
    tle_line1: str = Field(..., description="Raw TLE line 1, 69 chars, unmodified from source.")
    tle_line2: str = Field(..., description="Raw TLE line 2, 69 chars, unmodified from source.")
    epoch: datetime = Field(..., description="TLE epoch, UTC.")
    epoch_age_hours: float = Field(..., ge=0, description="Hours since epoch at screening time.")
    object_type: ObjectType
    rcs_size: RcsSize
    radius_m: float = Field(..., gt=0, description="Assumed hard-body radius, metres.")
    perigee_km: float = Field(..., description="Perigee altitude, km, above spherical Earth.")
    apogee_km: float = Field(..., description="Apogee altitude, km, above spherical Earth.")
    inclination_deg: float = Field(..., ge=0, le=180)


class ObjectRef(BaseModel):
    """Minimal reference to a CatalogObject, embedded in a ConjunctionEvent."""

    norad_id: int = Field(..., ge=1)
    name: str = Field(..., min_length=1)


class ConjunctionEvent(BaseModel):
    """A screened close-approach event. Never carries a probability of collision.

    See root README, "Why we don't publish a probability of collision".
    """

    event_id: str = Field(..., description="UUID.")
    primary: ObjectRef
    secondary: ObjectRef
    tca: datetime = Field(..., description="Time of closest approach, UTC.")
    miss_distance_km: float = Field(..., ge=0)
    relative_velocity_km_s: float = Field(..., ge=0)
    radial_km: float = Field(..., description="Signed, primary's RTN radial axis.")
    in_track_km: float = Field(..., description="Signed, primary's RTN in-track axis.")
    cross_track_km: float = Field(..., description="Signed, primary's RTN cross-track axis.")
    combined_radius_m: float = Field(..., gt=0)
    risk_score: float = Field(..., ge=0, le=1, description="Composite score, NOT a probability.")
    risk_tier: RiskTier
    confidence: float = Field(..., ge=0, le=1)
    confidence_note: str
    max_epoch_age_hours: float = Field(..., ge=0)
    screened_at: datetime


class EpochAgeDistribution(BaseModel):
    p50: float = Field(..., ge=0)
    p90: float = Field(..., ge=0)
    max: float = Field(..., ge=0)


class CatalogStatus(BaseModel):
    """Health and funnel telemetry for the ingest + screening pipeline."""

    object_count: int = Field(..., ge=0)
    last_refresh: datetime
    next_refresh: datetime
    source: str
    epoch_age_hours: EpochAgeDistribution
    screening_window_hours: float = Field(..., gt=0)
    last_screen_duration_s: float = Field(..., ge=0)
    pairs_considered: int = Field(..., ge=0)
    pairs_fine_screened: int = Field(..., ge=0)
    events_found: int = Field(..., ge=0)
