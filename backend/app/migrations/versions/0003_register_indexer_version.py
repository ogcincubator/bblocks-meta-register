"""Add registers.indexer_version (forces reindex when indexer code changes, independent of
upstream register.json `modified`)

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "registers",
        sa.Column("indexer_version", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("registers", "indexer_version")