# Backend Implementation Status

This document tracks what's actually built in `backend/` versus what [02-viewer-application.md](02-viewer-application.md)
and [03-indexing-and-search.md](03-indexing-and-search.md) describe, so a future session doesn't have to re-derive it
from the code. Broad strokes only — read the docs above and the code itself for the rest.

## What's implemented

- **Data model**: `orgs` → `registers` → `bblocks` hierarchy as SQLAlchemy ORM (real FKs, relationships), plus
  `bblock_deps`/`register_deps`/`identifier_conflicts`/`crawl_runs` as plain SQLAlchemy Core tables (no FK on the
  dependency edges' target side, by design — see doc 02's "Identifier conflicts" and dependency graph sections).
  Migrations via Alembic, single revision `0001_initial.py` (see "Migration convention" below).
- **Crawler**: full pipeline per doc 02 minus embeddings — discovery (`meta-register.json`/`meta-register-orgs.json`),
  per-register fetch, change detection (`modified` timestamp equality), full-replace indexing (relational rows +
  dependency edges + identifier-conflict rejection), orphan cleanup, per-host throttling/backoff, bounded worker
  pool, failure isolation. Scheduled via a plain `asyncio` loop (`app/scheduler.py`), not a cron library — see that
  file's docstring for why.
- **API**: `/orgs`, `/registers`, `/bblocks` (list + detail, with outgoing/incoming dependency edges), `/admin/status`,
  `/admin/conflicts`, `/admin/reindex` — matches doc 02's endpoint table. `/admin/*` requires an `X-Admin-Api-Key`
  header if `BBLOCKS_ADMIN_API_KEY` is set (unset = unprotected, fine for local dev only).
- **`GET /bblocks?q=`** is a plain SQL `LIKE` over name/abstract/id — an explicit placeholder for doc 03's hybrid
  search, not a finished feature. The query param and response envelope are already shaped to match what doc 03
  will eventually replace it with.
- Self-migrates on startup (`app/db/migrate.py`, called from `app/main.py`'s lifespan) — no manual `alembic upgrade
  head` step needed for local dev.
- Verified against real production data: a full crawl cycle against the live meta-registry (35 registers) completes
  with zero errors as of this writing.

## What's deferred (not started)

- **All of doc 03**: FTS5 keyword search, `sqlite-vec` embeddings/chunking, hybrid ranking, ontology-term indexing
  and boosting. None of the chunk tables or embedding provider interface exist yet.
- **MCP server** (doc 02's "MCP interface" section) — not started.
- **Frontend integration** — the Nuxt frontend has no application logic yet; nothing consumes this API.
- **CI** — no GitHub Actions workflow runs `pytest`/`ruff` yet.
- **Docker** — `Dockerfile`/`.dockerignore` exist but the image has never actually been built/run; treat it as
  unverified until someone does `docker build` + `docker run` against it.

## Non-obvious gotchas hit while building this (read before touching the crawler/DAL)

- **SQLite needs `poolclass=StaticPool`, always** (`app/db/base.py::_make_engine`). SQLAlchemy's default pool for a
  file-based `aiosqlite` URL hands out up to 5 separate physical connections; concurrent crawler tasks got different
  connections, one uncommitted transaction's rows not visible to another, and it caused deep confusion during
  bring-up (misdiagnosed as a concurrency bug initially — see the flush issue below, which was the actual cause of
  what was thought to be this). A serializing `asyncio.Lock` around session checkout (`_db_lock`) additionally
  ensures the one shared connection is never used by two coroutines at once. Trade-off: this serializes API reads
  behind crawler writes, sacrificing WAL's concurrent-readers benefit — acceptable at this catalog's scale (doc 03:
  "hundreds to low thousands of items"), revisit with a dedicated writer engine + separate reader pool if it
  matters later.
- **`session.flush()` before any raw Core `insert()`/`delete()` that references a just-`session.add()`-ed ORM row.**
  SQLAlchemy autoflushes pending ORM state before a `select()`, but *not* before a Core `insert()`/`delete()`
  executed via `session.execute()`. `app/repositories/deps.py::replace_bblock_deps`/`replace_register_deps` insert
  into `bblock_deps`/`register_deps` right after the source bblock/register was upserted via the ORM — without an
  explicit `flush()` first, the FK on the source side failed because the row wasn't actually in the database yet.
  This was the real cause of the FK errors seen during bring-up (a red herring initially pointed at concurrency).
- **Real `register.json` differs from doc 02's idealized description**: `schema`/`shaclShapes` are objects keyed by
  media type, not a single URL (presence = "non-empty", not "field is set"); `dependsOn`/`isProfileOf` targets are
  sometimes `bblocks://itemIdentifier` URIs and sometimes bare `itemIdentifier` strings in the wild (normalized by
  stripping the scheme in `app/crawler/indexer.py::_normalize_target_id`); there's no register-level `imports`
  field, so `register_deps` is derived entirely by rolling up `bblock_deps` edges to the registers their source/
  target bblocks belong to.
- **The real meta-registry data had a bug** (some `register.json` URLs pointed at `.../register.json` instead of
  the actual `.../build/register.json` publish path) — since fixed upstream in `bblocks-meta-register-data`. Worth
  remembering if a "register 404s" report comes in again: check the upstream data before assuming a crawler bug.

## Migration convention (current stage only)

No real data is indexed anywhere yet, so schema changes should **amend `0001_initial.py` directly** and the dev DB
file gets deleted/recreated, rather than stacking new revision files. Switch to normal incremental migrations once
this is deployed somewhere with data worth preserving.
