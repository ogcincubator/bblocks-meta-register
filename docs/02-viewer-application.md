# Meta-Registry Viewer Application — Architecture Summary

## Problem

The meta-registry (see [01-overall-architecture.md](01-overall-architecture.md)) makes registers addressable by alias,
but it's still just a directory of pointers — `index.json` plus one `register.json` per org. There's no way for a human
to browse what's actually in the ecosystem: which bblocks exist, what they do, who maintains them, or which one fits a
given use case. This is the same gap npmjs, PyPI, or Crates.io fill for their respective package ecosystems.

## Concept

A web application — FastAPI backend + Vue/Nuxt frontend (`backend/`, `frontend/` in this repo) — that crawls every
register known to the meta-registry, indexes its contents, and exposes search/browse/detail views modeled on
npmjs-style package registries: an org/register listing, a search bar, and a detail page per bblock showing its
metadata, schema, and examples.

## Backend

Responsibilities, roughly in pipeline order:

1. **Discovery** — fetch the two meta-registry index files:
   - [`https://w3id.org/ogc/bblocks/meta-register.json`](https://w3id.org/ogc/bblocks/meta-register.json) —
     the compiled identifier → `register.json` URL map (the main index).
   - [`https://w3id.org/ogc/bblocks/meta-register-orgs.json`](https://w3id.org/ogc/bblocks/meta-register-orgs.json) —
     org-level metadata keyed by org identifier: `name`, `description`, `url`, `maintainers`
     (`[{github, email}]`), and `registers` (list of register names belonging to that org). This is the
     source of truth for org pages in the viewer — the main index carries only the identifier→URL mapping,
     so org display names and descriptions come from here.
2. **Fetch** — download each register's compiled `register.json`. What further source data to fetch
   (schemas, examples, JSON-LD contexts, SHACL shapes) depends on indexing strategy — see
   [03-indexing-and-search.md](03-indexing-and-search.md).
3. **Change detection** — check whether a register has changed since last indexed using the freshness
   markers `register.json` already publishes, rather than computing a separate hash: the register's
   top-level `modified` timestamp (bumped by the postprocessor on every run) for a cheap register-level
   skip, and each bblock's `dateOfLastChange` for a per-bblock diff within a register that did change (see
   [03-indexing-and-search.md](03-indexing-and-search.md#indexing-pipeline) for the diff algorithm).
4. **Index/reindex** — when a register is new or changed, diff its bblock list against what's stored and
   update only the bblocks that were added, changed, or removed — not a full rebuild of the register, and
   not a full rebuild of the whole index.
5. **Orphan cleanup** — after refetching the two index files, diff the *set of register URLs* itself
   against what's locally stored (not just each known register's bblock list). A register no longer listed
   — because its org removed it, or the org's namespace was revoked — gets deleted locally (cascading
   through its bblocks, chunks, and `bblock_uris` rows), the same way a removed bblock does within a
   register that's still present. This is a distinct case from a register that's merely temporarily
   unreachable (see [Failure isolation](#scheduling-concurrency-and-throttling) below), which should be
   left alone and retried, not deleted.
6. **Serve** — REST API for the frontend (see [API](#api) below).

### Scheduling, concurrency, and throttling

The crawl runs once at startup (so the index is populated before serving begins on an empty database) and
then on a recurring schedule, entirely in the background — it must never block request handling, since the
API should keep serving the last-good indexed state while a crawl is in progress.

- **Concurrency** is bounded at the register level — a fixed-size worker pool (e.g. 3 concurrent register
  crawls) — since the win comes from overlapping I/O-bound fetches to *different* hosts.
- **Throttling** is a separate, per-host concern layered underneath that pool, not the same knob: two
  registers can share a host (e.g. two orgs both on GitHub Pages, or one org running several registers),
  in which case the register-level concurrency limit alone wouldn't stop several workers from hitting that
  host at once. A per-host rate limiter in the shared HTTP client enforces this regardless of which
  register-level worker issues the request.
- **Failure isolation** — a fetch or parse failure for one register (or one bblock within a register)
  is logged and skipped, not allowed to abort the whole crawl cycle; it's picked up again on the next
  scheduled run. A `429`/`5xx` response triggers exponential backoff on that host (part of the same
  per-host throttling mechanism, not a separate one) before the retry, rather than hammering a host that's
  already signaling it's overloaded.
- **Write serialization** — SQLite allows a single writer at a time. Fetching, parsing, and embedding stay
  concurrent across the worker pool, but the actual database writes (relational rows, FTS rows, vector
  chunks) are funneled through one writer path, with the database in WAL mode so concurrent readers
  (the API serving requests) aren't blocked by it.

### `register.json` structure

Each register publishes a `register.json` at its root that lists all its bblocks. The fields most relevant
to the viewer are listed below; for the full schema and authoring details, consult the **bblocks-authoring
skill** (available to agents working in this repo — see `bblock.schema.yaml` linked from that skill).

| Field | Notes |
|-------|-------|
| `itemIdentifier` | Globally unique dot-separated string, e.g. `ogc.geo.features.feature`. Auto-generated; do not set manually. |
| `name` | Display name. |
| `abstract` | Short description (Markdown). |
| `status` | Lifecycle status: `under-development`, `experimental`, `stable`, `superseded`, `retired`, etc. |
| `itemClass` | Block type: `schema`, `datatype`, `api`, `model`, `requirements-class`, etc. |
| `version` | Version string. |
| `tags` | Array of free-text strings. |
| `dateTimeAddition` / `dateOfLastChange` | ISO 8601 timestamps. |
| `schema` | URL to annotated JSON Schema (present if the block has a schema). |
| `ldContext` | URL to assembled JSON-LD context (present if the block has one). |
| `shaclShapes` | Array of SHACL shape file URLs (present if the block has shapes). |
| `dependsOn` | Array of `bblocks://` URIs for blocks this one has a runtime dependency on. |
| `isProfileOf` | `bblocks://` URI(s) of the block(s) this one profiles. |
| `sources` | Array of `{ title, link }` objects — specs or papers the block is based on. |

The `schema`, `ldContext`, `shaclShapes` fields drive the presence/absence badge row on bblock detail
pages. The `dependsOn` and `isProfileOf` fields are the raw material for the dependency graph.

### Identifier conflicts

`itemIdentifier` is supposed to be globally unique, but nothing enforces that across independently-hosted
registers — a typo, a copy-paste, or a genuine namespace squat could produce two registers claiming the
same id. When indexing a bblock whose id already exists under a *different* `register_url` than the one
currently being crawled, the existing owner wins: the incoming bblock is rejected rather than silently
overwriting/reassigning ownership. The rejection is recorded in a small `identifier_conflicts` table
(conflicting id, the register that already owns it, the register that tried to claim it, timestamp) rather
than just logged — a table survives process restarts and accumulates across crawl cycles until someone
fixes the upstream register, whereas an in-memory list would reset on every backend restart and could lose
a conflict that only reproduces once a week. This is what the `/admin/conflicts` endpoint below reads from.

### Storage

SQLite is the intended storage backend for both relational metadata and search, keeping the full storage
layer as one or two files — straightforward to deploy as a Docker volume.

- **Relational metadata** — orgs, registers, bblocks, change-detection state (content hash per register).
  Standard SQLite tables; the source of truth for listings and detail pages. Avoids holding all register
  data in memory during reindexing — load what changed, write it back.
- **Keyword search** — SQLite FTS5 over `name`, `abstract`, `tags`, and `itemIdentifier`.
- **Semantic search** — embeddings stored and queried via the
  [`sqlite-vec`](https://github.com/asg017/sqlite-vec) extension, which adds vector similarity search
  natively to SQLite without a separate vector database. A multilingual embedding model lets queries in
  different languages resolve to the same vector space. If scale or query volume eventually outgrows
  SQLite, replacing `sqlite-vec` with a dedicated store (Qdrant, Chroma) is a contained change. The
  embedding provider/model identifier used to produce each vector is recorded alongside it (see
  [03-indexing-and-search.md](03-indexing-and-search.md) for where) so that switching providers or models
  later is a detectable, triggerable full re-embed rather than silently mixing vectors from two different,
  incompatible embedding spaces in the same table.
- **Hybrid search** — FTS5 for exact identifier/acronym lookups (where embeddings perform poorly) +
  `sqlite-vec` for semantic queries, combined or switchable per query type.

**Write access**: [`aiosqlite`](https://github.com/omnilib/aiosqlite) is the intended driver — it runs one
dedicated background thread per connection and funnels every operation through an internal queue to that
thread, which gives single-writer serialization for free. This pairs naturally with `asyncio`-based crawl
orchestration (see [Scheduling, concurrency, and throttling](#scheduling-concurrency-and-throttling) above):
fetch/parse/embed stay concurrent across crawler tasks, while each `await conn.execute(...)` serializes
through that one thread without any additional locking code.

**Migrations**: schema changes are managed with [Alembic](https://alembic.sqlalchemy.org/) from the start,
rather than the ad hoc `CREATE TABLE IF NOT EXISTS` scripts common in early-stage prototypes — retrofitting
migration tooling after real data exists is far more painful than adopting it up front. Alembic's "batch
mode" handles SQLite's limited `ALTER TABLE` support (recreate-table-and-copy under the hood, automatic).
The FTS5 and `sqlite-vec` virtual tables (`CREATE VIRTUAL TABLE ...`) aren't things Alembic has declarative
ops for, but that's not a blocker — they're expressed as raw SQL via `op.execute()` inside a migration like
any other non-standard DDL.

Indexing strategy and embedding model selection are covered in
[03-indexing-and-search.md](03-indexing-and-search.md).

### API

FastAPI backend. The API is for the viewer frontend only — not a general-purpose interoperability
endpoint — so the design should optimize for that, not for OGC client conformance.

**On OGC API Records:** Records is designed for flat or lightly-structured catalogs. Our 3-level
structure (org → register → bblock) doesn't fit naturally — making each `@org/register` a collection
and adding a synthetic `_orgs` collection would be workable but is genuine shoehorning: it constrains
the response shape without benefiting anything, since no OGC Records client is consuming this API.

Recommended approach: **Records-inspired, not Records-conformant.** The `/bblocks` endpoint is
essentially a flat catalog of items — adopt Records-compatible query parameter conventions (`q`,
property filters, `limit`/`offset`, `numberMatched`/`numberReturned` response envelope) so that a
Records conformance facade could be added later if it becomes relevant. For `/orgs` and `/registers`,
use clean REST with the same paging conventions.

Intended resource endpoints:

| Endpoint | Description |
|----------|-------------|
| `GET /orgs` | List all organizations (sourced from `meta-register-orgs.json`). |
| `GET /orgs/{org}` | Single org metadata + its registers. |
| `GET /registers` | List all registers (optional `?org=` filter). |
| `GET /registers/{org}/{register}` | Single register metadata + bblock listing. |
| `GET /bblocks` | Search/list all bblocks — the main Records-compatible endpoint. |
| `GET /bblocks/{identifier}` | Single bblock metadata. |

No authentication — the public API is read-only.

A separate `/admin` group covers operational visibility into the background crawl, kept apart from the
public API namespace so it's easy to gate behind auth later without renaming anything:

| Endpoint | Description |
|----------|-------------|
| `GET /admin/status` | Crawl health: last successful run per register, current in-progress crawl state, recent failures. |
| `GET /admin/conflicts` | Unresolved `itemIdentifier` conflicts (see [Identifier conflicts](#identifier-conflicts) above). |
| `POST /admin/reindex` | Trigger an out-of-schedule crawl (optionally scoped to one register). |

These start unauthenticated like the rest of the API, but are namespaced so that password-protecting them
later (once the deployment is exposed somewhere that matters) is a middleware/auth-dependency addition, not
a breaking URL change for existing consumers.

### MCP interface

In addition to the REST API, the backend will expose an **MCP (Model Context Protocol) server** so that
AI agents and LLM-powered tools can interact with the meta-register directly. The MCP surface is
oriented toward reasoning and traversal tasks that are awkward over plain REST:

- **Use-case search** — given a natural-language problem statement or use case description, find the
  most suitable set of bblocks (uses the semantic/hybrid search index under the hood).
- **Dependency traversal** — given a bblock or register identifier, walk the dependency graph in either
  direction (what does X depend on? what depends on X?) to a specified depth.
- **Register inspection** — browse orgs, registers, and bblock listings as structured tool calls,
  suitable for an agent building context before recommending or composing bblocks.

This makes the meta-register a first-class tool for agents tasked with modelling, data integration, or
standards alignment work — rather than requiring them to parse REST responses and traverse links manually.

### Data model (sketch)

Relational metadata (orgs, registers, bblocks, maintainers, change-detection hashes) lives in SQLite.
The vector index for semantic search lives alongside it (same file via `sqlite-vec`, or a sidecar file).
See [Storage](#storage) above.

Dependency relationships are stored as explicit edge tables — one for register→register edges, one for
bblock→bblock edges — each row being `(source_id, target_id, kind)` where `kind` distinguishes
`imports`/`dependsOn`/`isProfileOf` etc. **No foreign key constraint** on `target_id`: crawl order isn't
guaranteed to index a dependency's target before the bblock that references it (the target might live in a
register that hasn't been crawled yet, or, at the edges, might reference a register outside the
meta-registry entirely). The edge is recorded regardless, and resolves to a live, navigable link once (and
if) its target is indexed — until then it just renders as a plain reference. Storing edges directionally
(source → target) means both outgoing and incoming queries are just index scans in opposite directions:

```sql
-- outgoing: what does X depend on?
SELECT target_id FROM bblock_deps WHERE source_id = ?
-- incoming: what depends on X?
SELECT source_id FROM bblock_deps WHERE target_id = ?
```

This is the structure needed to generate dependency graphs efficiently without full-table scans or
holding the whole graph in memory.

## Frontend

Nuxt/Vue app, npmjs-like in spirit, built with **Vuetify + Tailwind CSS** together — there's official guidance on
combining the two (Tailwind for layout/spacing utilities, Vuetify for components), and this is the same stack already
used in another of our applications, so we have a working reference to follow rather than figuring out the integration
from scratch.

### Three levels, not two

Conventional package registries are flat (org → package). We have an extra level: **organization → register →
bblock**. This shapes both navigation and search:

- **Search** is primarily over **registers** and **bblocks** — orgs are a grouping, not a search target in their own
  right.
- **Org pages** are just a listing of that org's registers (metadata + links), not a search surface.
- **Register pages** and **bblock pages** are the two real content views.

### Register and bblock views — deliberately minimal

[`bblocks-viewer`](https://github.com/ogcincubator/bblocks-viewer) is the existing full-featured renderer for a *single* register (tree
navigation, schema/example/JSON-LD/SHACL tabs, code viewers, ontology lookups, etc.). The meta-register viewer is not
trying to replace or re-implement that — it's a catalog/discovery layer across *all* registers, so its per-item views
should stay intentionally shallow:

- **Register view**: metadata (org, description, maintainers, source URL) + a list or graph of its bblocks. No schema
  rendering, no example viewers — link out to the canonical `bblocks-viewer`-style view (the register's own hosted
  viewer, if it has one) for that.
- **Bblock view**: metadata page + a row of icons/badges for whatever the bblock actually has (schema, examples,
  JSON-LD context, SHACL shapes, transforms, tests, status) — presence/absence at a glance, not the content itself.

### Dependencies and reverse dependencies

Dependency relationships are a first-class feature, at both levels:

- **Register-level**: which other registers a register imports (`imports` in `bblocks-config.yaml`, or in the
  `bblocks://@org/register/...` form once that's supported — see
  [01-overall-architecture.md](01-overall-architecture.md)).
- **Bblock-level**: which other bblocks a given bblock depends on.

These are worth highlighting especially when the dependency target is *also* in the meta-registry (a known
`@org/register` alias) — at that point the viewer can render it as a live, navigable link rather than just text.

**Reverse dependencies are the differentiating feature.** A single register's own viewer can only ever show outgoing
links — it has no way to know who depends on *it*. The meta-register viewer, because it has crawled and indexed every
known register, can compute and surface the reverse edges too: "registers that import this register," "bblocks that
depend on this bblock." This is information that doesn't exist anywhere else today, and is one of the strongest
reasons for the viewer to exist beyond search.

Implementation note: this implies the backend's data model needs an explicit dependency graph (register→register,
bblock→bblock), built during indexing, queryable in both directions — not just embedded/denormalized into each
register's or bblock's own metadata.

## Deployment

Both services ship as Docker images:

- **Backend** — FastAPI app container. Mounts a volume for the SQLite database file(s). Runs the
  crawl/reindex loop on a schedule (or triggered externally).
- **Frontend** — Nuxt app, either served as a Node.js SSR container or generated as static files
  (`yarn generate`) and served from a CDN/static host.

## Relationship to the Meta-Registry

This application is a *consumer* of the meta-registry, not a replacement for it — the meta-registry remains the
authoritative, lightweight alias→URL map that `bblocks-config.yaml` resolves against at build time. The viewer adds a
read-oriented, human-facing layer on top, rebuilt from the same source data.

## Status

Early design stage — `backend/` and `frontend/` are currently empty/scaffold-only. This document captures direction,
not a committed implementation plan; the indexing and search strategy in particular is covered in
[03-indexing-and-search.md](03-indexing-and-search.md).