"""Initial schema: orgs, registers, bblocks, dependency edges, conflicts, crawl runs, search indexes

Revision ID: 0001
Revises:
Create Date: 2026-07-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.config import settings
from app.search.keyword_index import create_fts_table, FTS_TABLE
from app.search.vector_store import create_vector_table, VECTOR_TABLE

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "orgs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("url", sa.String(), nullable=True),
        sa.Column("maintainers", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "registers",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("register_url", sa.String(), nullable=False),
        sa.Column("viewer_url", sa.String(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("modified", sa.String(), nullable=True),
        sa.Column("last_crawled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_crawl_status", sa.String(), nullable=True),
        sa.Column("last_error", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("register_url"),
    )
    op.create_index("ix_registers_org_id", "registers", ["org_id"])

    op.create_table(
        "bblocks",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("register_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("abstract", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("item_class", sa.String(), nullable=True),
        sa.Column("version", sa.String(), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("date_time_addition", sa.String(), nullable=True),
        sa.Column("date_of_last_change", sa.String(), nullable=True),
        sa.Column("has_schema", sa.Boolean(), nullable=False),
        sa.Column("has_ld_context", sa.Boolean(), nullable=False),
        sa.Column("has_shacl_shapes", sa.Boolean(), nullable=False),
        sa.Column("schema_urls", sa.JSON(), nullable=False),
        sa.Column("ld_context_url", sa.String(), nullable=True),
        sa.Column("shacl_shapes_urls", sa.JSON(), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["register_id"], ["registers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bblocks_register_id", "bblocks", ["register_id"])
    op.create_index("ix_bblocks_item_class", "bblocks", ["item_class"])

    op.create_table(
        "bblock_deps",
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("target_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["bblocks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("source_id", "target_id", "kind"),
    )
    op.create_index("ix_bblock_deps_target_id", "bblock_deps", ["target_id"])

    op.create_table(
        "register_deps",
        sa.Column("source_register_id", sa.String(), nullable=False),
        sa.Column("target_register_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["source_register_id"], ["registers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("source_register_id", "target_register_id", "kind"),
    )
    op.create_index("ix_register_deps_target_register_id", "register_deps", ["target_register_id"])

    op.create_table(
        "identifier_conflicts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conflicting_id", sa.String(), nullable=False),
        sa.Column("existing_register_id", sa.String(), nullable=False),
        sa.Column("attempted_register_id", sa.String(), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_identifier_conflicts_conflicting_id", "identifier_conflicts", ["conflicting_id"])

    op.create_table(
        "crawl_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("register_id", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_crawl_runs_register_id", "crawl_runs", ["register_id"])

    # sqlite-vec/FTS5 virtual tables aren't representable as SQLAlchemy Core metadata (no
    # op.create_table equivalent), so they're created via the same raw-DDL helpers
    # app/search/vector_store.py and app/search/keyword_index.py use for test setup -- one
    # definition of the schema, not two. docs/03-indexing-and-search.md.
    connection = op.get_bind()
    create_vector_table(connection.connection.dbapi_connection, dimensions=settings.embedding_dimensions)
    create_fts_table(connection.connection.dbapi_connection)


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {FTS_TABLE}")
    op.execute(f"DROP TABLE IF EXISTS {VECTOR_TABLE}")
    op.drop_table("crawl_runs")
    op.drop_table("identifier_conflicts")
    op.drop_table("register_deps")
    op.drop_table("bblock_deps")
    op.drop_table("bblocks")
    op.drop_table("registers")
    op.drop_table("orgs")
