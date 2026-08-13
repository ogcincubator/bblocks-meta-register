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

bblock_uris = Table(
    "bblock_uris",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    # FK (unlike bblock_deps.target_id): a semantic binding's URI is external vocabulary, not a
    # reference to another bblock, so there's no "dangling target" case to accommodate here --
    # bblock_id always points at a bblock this same crawl cycle just indexed. CASCADE means
    # delete_bblocks_for_register()'s full-replace wipes these for free, same reasoning as
    # bblock_deps.source_id.
    Column("bblock_id", ForeignKey("bblocks.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("uri", String, nullable=False, index=True),
    # Best-effort, dot-joined property path (e.g. "location.lat") to the property this URI was
    # bound to -- see docs/06-semantic-binding-lookup-plan.md's "ref/defs deduplication" note:
    # relative to the referencing property for defs-derived entries, not always absolute from
    # the doc root. Carried along purely for eyeballing/debugging, not queried on. For an
    # "example"-sourced row (see below) this is "example:<title>" instead of a schema path --
    # still just eyeballing/debugging material, never queried on.
    Column("path", String, nullable=True),
    # "schema" (resolvedProperties.json's effectiveId -- the bblock's author declared this
    # binding) or "example" (scraped from a Turtle example snippet -- the bblock merely
    # *uses* the term in sample data, not a declared binding). Used as a ranking tiebreaker
    # in find_bblocks_by_uri: a declared binding should outrank an incidental one at the same
    # match_type. See docs/06-semantic-binding-lookup-plan.md's "Example-derived bindings"
    # addendum.
    Column("source", String, nullable=False, server_default="schema"),
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
