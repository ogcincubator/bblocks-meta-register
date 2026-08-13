"""Add bblock_uris.source (declared "schema" binding vs. incidental "example" usage)

See docs/06-semantic-binding-lookup-plan.md's "Example-derived bindings" addendum.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "bblock_uris",
        sa.Column("source", sa.String(), nullable=False, server_default="schema"),
    )


def downgrade() -> None:
    op.drop_column("bblock_uris", "source")