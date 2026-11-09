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

from sqlalchemy import DDL, Column, DateTime, ForeignKey, Integer, MetaData, String, Table, event

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

# Facts: the `imports` a register.json declares (register.json URLs), stored verbatim and
# unresolved. Resolution to a registers.id happens at read time in the register_deps view below,
# so crawl order doesn't matter and nothing here can go stale when a target is delisted or
# re-URLed. Full-replaced per source register on every reindex (see replace_register_imports).
register_imports = Table(
    "register_imports",
    metadata,
    Column("source_register_id", ForeignKey("registers.id", ondelete="CASCADE"), primary_key=True),
    # No FK: the imported register may not be known to the meta-registry (or crawled yet).
    # Indexed anyway -- the register_deps view joins registers.register_url against it.
    Column("target_url", String, primary_key=True, index=True),
)

# register_deps is a *view*, not a table: register-level edges are derived at read time from
# bblock_deps (rolled up to the registers owning each end) plus register_imports (resolved by
# register.json URL). It lives on its own MetaData so Alembic autogenerate and create_all don't
# treat it as a table; the CREATE VIEW is emitted after register_imports is created (see the
# DDL listener below, which also covers tests' metadata.create_all) and by migration 0007.
REGISTER_DEPS_VIEW_SQL = """
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

event.listen(register_imports, "after_create", DDL(REGISTER_DEPS_VIEW_SQL))
event.listen(register_imports, "before_drop", DDL("DROP VIEW IF EXISTS register_deps"))

_view_metadata = MetaData()
register_deps = Table(
    "register_deps",
    _view_metadata,
    Column("source_register_id", String),
    Column("target_register_id", String),
    Column("kind", String),
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
    # "ontology" (a term the bblock's own ontology file defines -- see chunking.py's
    # _ontology_bindings()), "schema" (resolvedProperties.json's effectiveId -- the bblock's
    # author declared this binding to an external term), or "example" (scraped from a Turtle
    # example snippet -- the bblock merely *uses* the term in sample data, not a declared
    # binding). Used as a ranking tiebreaker in find_bblocks_by_uri: "ontology" > "schema" >
    # "example" (see repositories/bblock_uris.py's _SOURCE_RANK). See
    # docs/06-semantic-binding-lookup-plan.md's "Example-derived bindings" / "Ontology-derived
    # bindings" addenda.
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
