"""add anki publications

Revision ID: 61df1b1bdad7
Revises: dfd8206eedfc
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "61df1b1bdad7"
down_revision: str | None = "dfd8206eedfc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "anki_publications",
        sa.Column("note_id", sa.String(length=36), nullable=False),
        sa.Column("anki_note_id", sa.Integer(), nullable=True),
        sa.Column("target_deck", sa.String(length=256), nullable=False),
        sa.Column("target_note_type", sa.String(length=256), nullable=False),
        sa.Column("published_version", sa.Integer(), nullable=True),
        sa.Column("publishing_version", sa.Integer(), nullable=True),
        sa.Column("published_hash", sa.String(length=64), nullable=True),
        sa.Column("observed_anki_hash", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_error_code", sa.String(length=128), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_anki_publications_attempt_nonnegative"),
        sa.ForeignKeyConstraint(["note_id"], ["notes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("note_id"),
        sa.UniqueConstraint("anki_note_id"),
    )


def downgrade() -> None:
    op.drop_table("anki_publications")
