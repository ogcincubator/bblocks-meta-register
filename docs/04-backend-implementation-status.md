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
- **`GET /bblocks?q=`** is doc 03's hybrid search (see below), not the earlier `LIKE` placeholder.
- **MCP server** (`app/mcp/server.py`, doc 02's "MCP interface" section): mounted at `/mcp` on the same FastAPI
  app/process (not a separate server) via the official `mcp` Python SDK's streamable-HTTP ASGI app, so it shares
  the process-global SQLite engine instead of needing its own DB connection handling. Nine tools: `search_bblocks`
  (the hybrid search, for use-case/natural-language queries), `list_bblocks_tool` (plain filtered browse),
  `get_bblock`/`get_register`/`get_org` (detail, same shape as the REST endpoints), `list_registers_tool`/
  `list_orgs_tool`, and `bblock_dependencies`/`register_dependencies` (depth-limited BFS over the dependency edge
  tables in either direction -- doc 02's "dependency traversal" tool, not exposed over REST at all). `/mcp` is
  unauthenticated and open to any client by default, same as `/orgs`/`/registers`/`/bblocks` -- deliberately, since
  the whole point is letting any LLM tooling reach it. `BBLOCKS_MCP_ALLOWED_HOSTS`/`BBLOCKS_MCP_ALLOWED_ORIGINS`
  (see `.env.example`) exist only as an optional Host/Origin allowlist if this ever needs restricting later; unset
  (the default) disables the check entirely, since the MCP SDK's own built-in protection would otherwise reject
  non-localhost requests out of the box.
- Self-migrates on startup (`app/db/migrate.py`, called from `app/main.py`'s lifespan) — no manual `alembic upgrade
  head` step needed for local dev.
- Verified against real production data: a full crawl cycle against the live meta-registry (35 registers) completes
  with zero errors as of this writing.

## Hybrid search (`app/search/`)

Doc 03's keyword + semantic hybrid search, minus ontology-term boosting (see "What's deferred" below).

- **Embeddings** (`embeddings.py`): `EmbeddingProvider` Protocol with `OllamaEmbeddingProvider` (priority
  implementation — self-hosted, no external dependency; task-prefixes inputs `search_document: `/`search_query: `
  per the `nomic-embed-text-v2-moe` family's expected usage) and `OpenAICompatibleEmbeddingProvider`. Selected via
  `BBLOCKS_EMBEDDING_PROVIDER`; default model is `nomic-embed-text-v2-moe:latest` against a local Ollama at
  `localhost:11434`, 768 dimensions.
- **Vector store** (`vector_store.py`): a `sqlite-vec` `vec0` virtual table (`vector_chunks`), cosine distance.
  `org`/`register_url` are vec0 partition-key columns; `chunk_type`/`bblock_id`/`item_class`/`status` are plain
  metadata columns — all filterable during the KNN scan itself, not via a post-hoc join (doc 03's correctness
  requirement for top-K filtering). Rowids are a stable hash of a chunk key, not autoincrement, so re-indexing the
  same bblock/register overwrites rather than duplicates.
- **Keyword index** (`keyword_index.py`): a standalone FTS5 table (`bblocks_fts`), not an external-content table
  (see gotchas below for why), kept in sync explicitly at the same points the crawler already full-replaces a
  register's bblocks. Same `org`/`item_class`/`status` filter columns as the vector store.
- **Chunking** (`chunking.py`): builds `register_summary`, `bblock_core`, `bblock_schema`, and `bblock_examples`
  (from the per-bblock `documentation.json-full` doc, since register.json itself has no inline example content)
  chunks per doc 03. `bblock_schema` prefers `ldContext` over `annotatedSchema`/`resolvedSchemaProperties` — the
  JSON-LD context's field→URI bindings already reflect imported/profiled schemas' properties, where the raw schema
  would still need `$ref` resolution to see them — but falls back to `resolvedSchemaProperties` (property names,
  no URIs) when a bblock has no `ldContext` at all, so schema-only bblocks still get a `bblock_schema` chunk
  instead of silently getting none (hit in the wild: 1 of 25 bblocks in the `bblocks-examples` register). A fetch
  failure for one bblock's extra content is logged and skipped, not allowed to abort the register's reindex.
- **Search service** (`service.py`): keyword pass (FTS5, bm25) + semantic pass (best chunk per bblock) merged so a
  keyword hit is guaranteed inclusion, `rank_score = max(keyword_score, semantic_score)`. Filters (`org`,
  `register`, `item_class`, `status`) apply identically to both passes before merging. Candidate pool size per pass
  is bounded (`BBLOCKS_SEARCH_KEYWORD_CANDIDATES`/`BBLOCKS_SEARCH_SEMANTIC_CANDIDATES`, default 50 each) — at
  larger result-set sizes this could under-fill a requested page past the candidate pool; untested at that scale.
- Wired into the crawler: `app/crawler/indexer.py::index_search_content`, called from the orchestrator right after
  the relational `index_register`, in the same per-register try/except — an embedding-provider failure (e.g.
  Ollama unreachable) currently fails that register's whole crawl run, relational rows included, not just the
  search indexes. Full-replace per register, same as the relational tables.

## What's deferred (not started)

- **Ontology-term indexing and boosting** (doc 03's "Ontology-term indexing and boosting" section) — no
  `ontologies`/`bblock_uris` tables, no boost pass in the search service. This also means the MCP server's
  `search_bblocks` tool doesn't get ontology-term boosting either, since it shares the same `hybrid_search`.
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
- **`sqlite-vec`'s extension-loading methods are awaitable-only on aiosqlite's driver connection**
  (`app/db/base.py::_make_engine`'s `connect` event handler) — `enable_load_extension`/`load_extension` aren't
  present on the sync-looking `AsyncAdapt_aiosqlite_connection` SQLAlchemy hands the event handler; the fix is
  `dbapi_connection.run_async(...)`, SQLAlchemy's documented pattern for calling async-only driver methods from a
  sync pool event handler. Any test engine built via a bare `create_async_engine(...)` instead of `_make_engine`
  won't have the extension loaded and any `vec0`/FTS5 virtual table operation will fail — `tests/conftest.py`'s
  `db_engine` fixture uses `_make_engine` for this reason.
- **vec0 `TEXT` metadata columns reject `NULL` outright** (`app/search/vector_store.py`) — a chunk with no
  `bblock_id`/`item_class`/`status` (e.g. a `register_summary` chunk) stores `""` instead and translates back to
  `None` at the read boundary, rather than storing `NULL`.
- **vec0's default distance metric is L2, not cosine** — doc 03 assumes cosine similarity throughout; the vec0
  table is created with `distance_metric=cosine` explicitly (easy to miss, since `CREATE VIRTUAL TABLE ... USING
  vec0(embedding float[N])` silently accepts the omission and just computes the wrong thing).
- **FTS5 is a standalone table, not `bblocks`' external-content table** — `bblocks.id` is a `TEXT` primary key, and
  FTS5 external-content tables require an integer rowid matching the content table's rowid. Kept in sync explicitly
  instead (see `keyword_index.py`'s module docstring).
- **respx 0.21.1 (the version originally pinned in `pyproject.toml`) is incompatible with httpx 0.28** — any
  `respx.mock`-decorated test raised `AllMockedAssertionError` even for a route that was clearly registered,
  because respx's internal transport hooks didn't match httpx 0.28's internals. Bumped the constraint to
  `respx ^0.22` and ran `poetry update respx` to fix; if a future respx-based test mysteriously reports "not
  mocked" for an obviously-matching route, check the respx/httpx version pairing before assuming a routing bug.

- **FastMCP's `streamable_http_app()` sub-app has its own lifespan that mounting alone never runs** — Starlette's
  `Mount` only forwards `http`/`websocket` ASGI scopes to a sub-app, never `lifespan` (`Mount.matches()` explicitly
  checks for those two scope types only), so `app.mount("/mcp", mcp.streamable_http_app())` silently leaves the MCP
  session manager never started; every request would hang or error. Fixed in `app/main.py`'s `lifespan()` by
  entering `mcp.session_manager.run()` manually alongside the crawl loop's task. `mcp.session_manager` is only
  constructed lazily by `streamable_http_app()`, so that has to be called (and its result mounted) before the
  `FastAPI(lifespan=...)` app that references `mcp.session_manager` is even built.
- **FastMCP's own default `streamable_http_path` is `/mcp`**, same as the mount path used in `app/main.py` — left
  at its default, the effective route becomes `/mcp/mcp`. `app/mcp/server.py` sets `streamable_http_path="/"` when
  constructing `FastMCP(...)` to avoid the doubled segment.
- **The MCP SDK's built-in DNS-rebinding protection only auto-enables for `host in ("127.0.0.1", "localhost",
  "::1")`, and even then only allows `Host` headers with an explicit port** (`allowed_hosts=["localhost:*", ...]`,
  no bare `"localhost"` entry) — a bare hostname (as a reverse proxy typically forwards) is rejected with 421
  regardless. Rolled a `BBLOCKS_MCP_ALLOWED_HOSTS`/`BBLOCKS_MCP_ALLOWED_ORIGINS`-driven `TransportSecuritySettings`
  instead of relying on the SDK's construction-time default (see `app/mcp/server.py`).

## Migration convention (current stage only)

No real data is indexed anywhere yet, so schema changes should **amend `0001_initial.py` directly** and the dev DB
file gets deleted/recreated, rather than stacking new revision files. Switch to normal incremental migrations once
this is deployed somewhere with data worth preserving.
