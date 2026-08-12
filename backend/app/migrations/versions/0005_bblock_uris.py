"""Add bblock_uris (semantic binding reverse index: bblock_id -> external RDF/vocabulary URI)

See docs/06-semantic-binding-lookup-plan.md.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bblock_uris",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bblock_id", sa.String(), nullable=False),
        sa.Column("uri", sa.String(), nullable=False),
        sa.Column("path", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["bblock_id"], ["bblocks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bblock_uris_bblock_id", "bblock_uris", ["bblock_id"])
    op.create_index("ix_bblock_uris_uri", "bblock_uris", ["uri"])


def downgrade() -> None:
    op.drop_index("ix_bblock_uris_uri", table_name="bblock_uris")
    op.drop_index("ix_bblock_uris_bblock_id", table_name="bblock_uris")
    op.drop_table("bblock_uris")
