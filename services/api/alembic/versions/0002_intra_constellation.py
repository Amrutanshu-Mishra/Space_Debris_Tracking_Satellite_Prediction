"""add conjunctions.intra_constellation

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-01

Adds the boolean flag set by prahari_orbital.scoring.is_intra_constellation:
both objects are active payloads of one station-kept constellation
(Starlink / OneWeb / Globalstar / Iridium). The list view excludes these by
default. server_default false keeps any rows written before this migration
valid; the loader repopulates the real value on the next ingest.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conjunctions",
        sa.Column(
            "intra_constellation",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("conjunctions", "intra_constellation")
