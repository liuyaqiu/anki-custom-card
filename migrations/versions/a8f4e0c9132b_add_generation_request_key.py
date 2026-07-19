"""add generation request key

Revision ID: a8f4e0c9132b
Revises: 61df1b1bdad7
Create Date: 2026-07-19 21:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a8f4e0c9132b"
down_revision: str | None = "61df1b1bdad7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("generation_jobs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("request_key", sa.String(length=64), nullable=True))
        batch_op.create_unique_constraint("uq_generation_jobs_request_key", ["request_key"])


def downgrade() -> None:
    with op.batch_alter_table("generation_jobs", schema=None) as batch_op:
        batch_op.drop_constraint("uq_generation_jobs_request_key", type_="unique")
        batch_op.drop_column("request_key")
