"""Normalised SQLAlchemy models for the optional Postgres backend.

These tables are storage-shaped, not wire-shaped. Deliberate differences
from ``contracts/schemas/`` (all covered in the README "Storage design"
section):

- A ``ConjunctionEvent`` nests ``primary``/``secondary`` object refs; the
  ``conjunctions`` table instead holds ``primary_norad_id`` /
  ``secondary_norad_id`` foreign keys into ``objects`` and reads the names
  back by join. The event's object refs are not stored twice.
- ``CatalogObject.epoch_age_hours`` is **not** a column. It is "hours since
  epoch at screening time" -- a value that goes stale the moment it is
  written. It is recomputed from ``objects.epoch`` and the wall clock in
  :func:`row_to_catalog_object` every time an object is serialised.
- ``CatalogStatus`` has no table. Its funnel counters live on
  ``screening_runs`` (one row per ingest of a screening result) and its
  epoch-age distribution is computed on demand from ``objects.epoch``.

No ``probability_of_collision`` / ``pc`` column exists here and none may be
added -- see the root ``CLAUDE.md``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    false,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ObjectRow(Base):
    """One tracked catalogue object. Maps to ``CatalogObject`` minus the
    derived ``epoch_age_hours`` (see module docstring)."""

    __tablename__ = "objects"

    norad_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    tle_line1: Mapped[str] = mapped_column(String(80), nullable=False)
    tle_line2: Mapped[str] = mapped_column(String(80), nullable=False)
    epoch: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    object_type: Mapped[str] = mapped_column(String(32), nullable=False)
    rcs_size: Mapped[str] = mapped_column(String(16), nullable=False)
    radius_m: Mapped[float] = mapped_column(Float, nullable=False)
    perigee_km: Mapped[float] = mapped_column(Float, nullable=False)
    apogee_km: Mapped[float] = mapped_column(Float, nullable=False)
    inclination_deg: Mapped[float] = mapped_column(Float, nullable=False)


class ScreeningRunRow(Base):
    """One ingest of a screening result. Backs the funnel half of
    ``CatalogStatus`` and stamps every ``conjunctions`` row it produced."""

    __tablename__ = "screening_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_hours: Mapped[float] = mapped_column(Float, nullable=False)
    objects_screened: Mapped[int] = mapped_column(Integer, nullable=False)
    pairs_considered: Mapped[int] = mapped_column(BigInteger, nullable=False)
    pairs_fine_screened: Mapped[int] = mapped_column(Integer, nullable=False)
    events_found: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_s: Mapped[float] = mapped_column(Float, nullable=False)


class ConjunctionRow(Base):
    """One screened close-approach event. Maps to ``ConjunctionEvent`` with
    the nested object refs flattened to foreign keys."""

    __tablename__ = "conjunctions"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    primary_norad_id: Mapped[int] = mapped_column(
        ForeignKey("objects.norad_id"), nullable=False
    )
    secondary_norad_id: Mapped[int] = mapped_column(
        ForeignKey("objects.norad_id"), nullable=False
    )
    tca: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    miss_distance_km: Mapped[float] = mapped_column(Float, nullable=False)
    relative_velocity_km_s: Mapped[float] = mapped_column(Float, nullable=False)
    radial_km: Mapped[float] = mapped_column(Float, nullable=False)
    in_track_km: Mapped[float] = mapped_column(Float, nullable=False)
    cross_track_km: Mapped[float] = mapped_column(Float, nullable=False)
    combined_radius_m: Mapped[float] = mapped_column(Float, nullable=False)
    risk_score: Mapped[float] = mapped_column(Float, nullable=False)
    risk_tier: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_note: Mapped[str] = mapped_column(Text, nullable=False)
    max_epoch_age_hours: Mapped[float] = mapped_column(Float, nullable=False)
    screened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Both objects are the same station-kept constellation (see
    # prahari_orbital.scoring.is_intra_constellation). The list view excludes
    # these by default. server_default keeps pre-existing rows valid.
    intra_constellation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false()
    )
    screening_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("screening_runs.id"), nullable=True
    )

    __table_args__ = (
        # The list view filters on tca window, tier, and score.
        Index("ix_conjunctions_tca", "tca"),
        Index("ix_conjunctions_risk_tier", "risk_tier"),
        Index("ix_conjunctions_risk_score", "risk_score"),
    )
