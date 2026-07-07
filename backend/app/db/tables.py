"""Plain SQLAlchemy Core tables (no ORM mapping, no relationship()).

Used for the dependency edge tables and admin/bookkeeping tables that are explicitly
designed (see docs/02-viewer-application.md) to allow dangling references -- e.g. a
dependency's target bblock/register may not be indexed yet, or may live outside the
meta-registry entirely. Modeling these with ORM relationship()s would assume the
referential integrity this data model deliberately doesn't have, so they're queried as
plain directional index scans instead (see app/repositories/deps.py).

Registered on the same MetaData as the ORM models (app/db/models.py) so Alembic
autogenerate diffs both together.
"""

import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Table

from app.db.base import metadata

bblock_deps = Table(
    "bblock_deps",
    metadata,
    Column("source_id", ForeignKey("bblocks.id", ondelete="CASCADE"), primary_key=True),
    # No FK: target may not be indexed yet (or ever, if it's outside the meta-registry).
    # Indexed anyway -- incoming_bblock_deps() (reverse-dependency lookups) filters on it.
    Column("target_id", String, primary_key=True, index=True),
    Column("kind", String, primary_key=True),  # "dependsOn" | "isProfileOf"
)

register_deps = Table(
    "register_deps",
    metadata,
    Column("source_register_id", ForeignKey("registers.id", ondelete="CASCADE"), primary_key=True),
    # No FK: target register may not be known/crawled yet. Indexed anyway -- reverse-lookup
    # queries (incoming_register_deps()) filter on it.
    Column("target_register_id", String, primary_key=True, index=True),
    Column("kind", String, primary_key=True),
)

identifier_conflicts = Table(
    "identifier_conflicts",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("conflicting_id", String, nullable=False, index=True),
    Column("existing_register_id", String, nullable=False),
    Column("attempted_register_id", String, nullable=False),
    Column(
        "detected_at",
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.datetime.now(datetime.UTC),
    ),
)

crawl_runs = Table(
    "crawl_runs",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    # Null register_id = whole-cycle row (discovery + orphan cleanup), not scoped to one register.
    Column("register_id", String, nullable=True, index=True),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("finished_at", DateTime(timezone=True), nullable=True),
    Column("status", String, nullable=False),  # "running" | "ok" | "error" | "skipped"
    Column("error", String, nullable=True),
)
