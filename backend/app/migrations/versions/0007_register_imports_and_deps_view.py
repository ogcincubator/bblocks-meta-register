"""Replace the materialized register_deps table with a view over bblock_deps + register_imports

Register-level dependencies were rolled up at index time, so crawl order could silently drop
edges (a target not yet indexed) and nothing re-resolved them. Now `register_imports` stores
the declared imports (register.json URLs) unresolved and `register_deps` is a view resolving
everything at read time. The old table's rows are dropped: they're fully re-derivable, and the
INDEXER_VERSION bump repopulates register_imports on the next crawl.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Keep in sync with app/db/tables.py::REGISTER_DEPS_VIEW_SQL (copied, not imported, so this
# migration stays a fixed snapshot).
VIEW_SQL = """
CREATE VIEW register_deps AS
SELECT sb.register_id AS source_register_id, tb.register_id AS target_register_id, bd.kind AS kind
FROM bblock_deps bd
JOIN bblocks sb ON sb.id = bd.source_id
JOIN bblocks tb ON tb.id = bd.target_id
WHERE sb.register_id != tb.register_id
UNION
SELECT ri.source_register_id, r.id, 'imports'
FROM register_imports ri
JOIN registers r ON r.register_url = ri.target_url
WHERE r.id != ri.source_register_id
"""


def upgrade() -> None:
    op.drop_table("register_deps")
    op.create_table(
        "register_imports",
        sa.Column("source_register_id", sa.String(), sa.ForeignKey("registers.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("target_url", sa.String(), primary_key=True),
    )
    op.create_index("ix_register_imports_target_url", "register_imports", ["target_url"])
    op.execute(VIEW_SQL)


def downgrade() -> None:
    op.execute("DROP VIEW register_deps")
    op.drop_index("ix_register_imports_target_url", table_name="register_imports")
    op.drop_table("register_imports")
    op.create_table(
        "register_deps",
        sa.Column("source_register_id", sa.String(), sa.ForeignKey("registers.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("target_register_id", sa.String(), primary_key=True),
        sa.Column("kind", sa.String(), primary_key=True),
    )
    op.create_index("ix_register_deps_target_register_id", "register_deps", ["target_register_id"])
