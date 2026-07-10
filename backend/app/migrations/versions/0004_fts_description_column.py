"""Add description column to bblocks_fts (keyword search now indexes bblock description
alongside name/abstract/tags/itemIdentifier)

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-10

"""
from typing import Sequence, Union

from alembic import op

from app.search.keyword_index import FTS_TABLE, create_fts_table

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # FTS5 tables aren't representable via op.add_column -- drop and recreate via the same
    # raw-DDL helper 0001_initial.py used. Existing rows are lost, but INDEXER_VERSION was
    # bumped alongside this migration (see app/crawler/change_detection.py) so every register
    # is force-reindexed on the next crawl cycle, repopulating this table with the new column.
    connection = op.get_bind()
    op.execute(f"DROP TABLE IF EXISTS {FTS_TABLE}")
    create_fts_table(connection.connection.dbapi_connection)


def downgrade() -> None:
    # create_fts_table() always reflects the current (post-migration) schema, so the pre-0004
    # column set is spelled out here rather than reused, to actually reverse this migration.
    op.execute(f"DROP TABLE IF EXISTS {FTS_TABLE}")
    op.execute(
        f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS {FTS_TABLE} USING fts5(
            bblock_id UNINDEXED,
            register_id UNINDEXED,
            org UNINDEXED,
            item_class UNINDEXED,
            status UNINDEXED,
            name,
            abstract,
            tags,
            item_identifier
        )
        """
    )
