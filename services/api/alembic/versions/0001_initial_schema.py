"""initial schema: objects, screening_runs, conjunctions

Revision ID: 0001
Revises:
Create Date: 2026-09-01

Matches prahari_api.db.tables. The list view filters on tca / risk_tier /
risk_score, so those are indexed; epoch_age_hours is intentionally absent
(computed at serialisation time).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "objects",
        sa.Column("norad_id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("tle_line1", sa.String(length=80), nullable=False),
        sa.Column("tle_line2", sa.String(length=80), nullable=False),
        sa.Column("epoch", sa.DateTime(timezone=True), nullable=False),
        sa.Column("object_type", sa.String(length=32), nullable=False),
        sa.Column("rcs_size", sa.String(length=16), nullable=False),
        sa.Column("radius_m", sa.Float(), nullable=False),
        sa.Column("perigee_km", sa.Float(), nullable=False),
        sa.Column("apogee_km", sa.Float(), nullable=False),
        sa.Column("inclination_deg", sa.Float(), nullable=False),
    )

    op.create_table(
        "screening_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_hours", sa.Float(), nullable=False),
        sa.Column("objects_screened", sa.Integer(), nullable=False),
        sa.Column("pairs_considered", sa.BigInteger(), nullable=False),
        sa.Column("pairs_fine_screened", sa.Integer(), nullable=False),
        sa.Column("events_found", sa.Integer(), nullable=False),
        sa.Column("duration_s", sa.Float(), nullable=False),
    )

    op.create_table(
        "conjunctions",
        sa.Column("event_id", sa.String(length=64), primary_key=True),
        sa.Column(
            "primary_norad_id",
            sa.Integer(),
            sa.ForeignKey("objects.norad_id"),
            nullable=False,
        ),
        sa.Column(
            "secondary_norad_id",
            sa.Integer(),
            sa.ForeignKey("objects.norad_id"),
            nullable=False,
        ),
        sa.Column("tca", sa.DateTime(timezone=True), nullable=False),
        sa.Column("miss_distance_km", sa.Float(), nullable=False),
        sa.Column("relative_velocity_km_s", sa.Float(), nullable=False),
        sa.Column("radial_km", sa.Float(), nullable=False),
        sa.Column("in_track_km", sa.Float(), nullable=False),
        sa.Column("cross_track_km", sa.Float(), nullable=False),
        sa.Column("combined_radius_m", sa.Float(), nullable=False),
        sa.Column("risk_score", sa.Float(), nullable=False),
        sa.Column("risk_tier", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("confidence_note", sa.Text(), nullable=False),
        sa.Column("max_epoch_age_hours", sa.Float(), nullable=False),
        sa.Column("screened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "screening_run_id",
            sa.Integer(),
            sa.ForeignKey("screening_runs.id"),
            nullable=True,
        ),
    )
    op.create_index("ix_conjunctions_tca", "conjunctions", ["tca"])
    op.create_index("ix_conjunctions_risk_tier", "conjunctions", ["risk_tier"])
    op.create_index("ix_conjunctions_risk_score", "conjunctions", ["risk_score"])


def downgrade() -> None:
    op.drop_index("ix_conjunctions_risk_score", table_name="conjunctions")
    op.drop_index("ix_conjunctions_risk_tier", table_name="conjunctions")
    op.drop_index("ix_conjunctions_tca", table_name="conjunctions")
    op.drop_table("conjunctions")
    op.drop_table("screening_runs")
    op.drop_table("objects")
