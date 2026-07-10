# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

`backend/` has a working FastAPI + crawler + hybrid-search scaffold (see `docs/04-backend-implementation-status.md`
and the Backend section below) — it is no longer empty, despite what older parts of the architecture docs imply.
`frontend/` is a freshly scaffolded Nuxt app with no application logic beyond the default Vuetify CLI template.
Read `docs/01-overall-architecture.md` and `docs/02-viewer-application.md` before making architectural decisions —
they describe two related but distinct pieces of this project (see below); treat their backend implementation
details as historical intent rather than current fact, and prefer reading the actual code/`docs/04-*` for
what's really there.

## What this repo is

Two related sub-projects living in one repo:

1. **The meta-registry** (`docs/01-overall-architecture.md`) — a planned GitHub-hosted directory (per-org
   `registers.yaml` files compiled into a flat `index.json`) that maps short aliases like `@acme/my-bblocks` to
   OGC Building Blocks register URLs, so `bblocks-config.yaml` `imports` entries don't have to hardcode raw URLs.
   This part is data/config-driven (YAML + a compiled JSON index), not application code.
2. **The viewer application** (`docs/02-viewer-application.md`, `backend/` + `frontend/`) — a FastAPI backend +
   Nuxt/Vue frontend that crawls every register known to the meta-registry, indexes its bblocks, and exposes an
   npmjs-style search/browse/detail UI across the whole ecosystem. This is a *catalog across all registers*, not a
   replacement for [bblocks-viewer](https://github.com/ogcincubator/bblocks-viewer) (the existing per-register
   detail renderer) — register/bblock detail pages here are intentionally shallow (metadata + presence/absence
   badges) and link out to the register's own hosted viewer for actual schema/example content.

Key architectural point carried through both docs: navigation/search has **three levels, not two** —
organization → register → bblock (unlike flat package registries such as npm). Reverse dependencies (which
registers/bblocks depend on a given one) are called out as a differentiating feature only the meta-register viewer
can provide, since a single register's own viewer only ever sees outgoing links.

## Frontend (`frontend/`)

Nuxt 4 + Vue 3 + Vuetify + Tailwind CSS, TypeScript, package manager **yarn** (not npm).

Commands (run from `frontend/`):
```bash
yarn install
yarn dev          # dev server
yarn build        # production build
yarn generate     # static generation
yarn preview      # preview a build
yarn lint         # eslint
yarn lint:fix
```

Structure:
- `app/app.vue` — main entry/root component
- `app/pages/` — routes
- `app/components/` — reusable components
- `app/assets/styles/` — `layers.css`, `tailwind.css`, `main.scss`, `settings.scss` (Vuetify style config)
- `app/plugins/` — Nuxt plugins

Vuetify + Tailwind are used together deliberately (Tailwind for layout/spacing utilities, Vuetify for components) —
this mirrors a pattern already used in another sibling project, so look there for working integration patterns
rather than re-deriving the setup. Theme defaults to `dark` (`nuxt.config.ts`); `ssr` is intentionally left enabled
(not `false`) for this default to avoid hydration warnings, per the comment in `nuxt.config.ts`.

`yarn mcp` / `yarn mcp:revert` apply/revert agent config via [ruler](https://github.com/intellectronica/ruler)
(`frontend/.ruler/ruler.toml`, `frontend/.ruler/AGENTS.md`) — this is how the Vuetify MCP server config gets
distributed to various agent tools. `frontend/AGENTS.md` is the ruler-managed output; edit `.ruler/AGENTS.md` as
the source of truth, not the generated one, if project rules need to change.

## Git workflow

Make topical commits: when a session produces several unrelated fixes/features, commit each
concern separately rather than bundling them into one commit. Before staging for a commit like
this, run `git reset .` first (safe — unstages everything, touches no working-tree content) so
a plain `git add <files>` can't sweep in other changes already staged in the index (e.g. the
user's own in-progress work staged from their terminal). Verify with `git status --short`
that only the intended files are staged before committing.

## Backend (`backend/`)

FastAPI app (async, SQLAlchemy + Alembic, poetry-managed — run `poetry run ...` for pytest/ruff/uvicorn, not raw
`.venv/bin/python3`). Implements the crawler, dependency graph, and hybrid
(embeddings + keyword) search described in `docs/02-viewer-application.md`; see `docs/04-backend-implementation-status.md`
for what's built vs. still open. Structure: `app/api` (REST routes), `app/crawler`, `app/db` (models + Alembic
migrations under `app/migrations`), `app/repositories`, `app/schemas`, `app/search` (hybrid search + embedding
provider), `app/services` (dependency graph traversal), `app/mcp` (see below). Tests in `backend/tests/`.

Run locally: `poetry run uvicorn app.main:app --reload --port 8000` (from `backend/`). This runs Alembic migrations
on startup, starts the register crawl loop, and mounts everything below.

`needs_reindex()` (`app/crawler/change_detection.py`) skips a register whose upstream `register.json` `modified`
timestamp hasn't changed — a bug in *this repo's* extraction/transform logic (e.g. `app/crawler/indexer.py`'s
`_extract_presence`/`_extract_edges`) would otherwise leave every already-crawled register stuck with the old,
wrong stored data until its upstream content happens to change next. Bump `INDEXER_VERSION` in
`change_detection.py` whenever such a change is made — every register is force-reindexed on the next crawl cycle
regardless of `modified` until its `registers.indexer_version` column catches up.

### MCP server (`app/mcp/server.py`)

A FastMCP server exposing the same catalog (search/browse/detail/dependency-traversal across orgs → registers →
bblocks) as MCP tools for LLM agents, mounted at `/mcp` on the FastAPI app (streamable HTTP transport) rather than
run as a separate process, so it shares the app's DB session factory. Tools: `search_bblocks` (hybrid
keyword+semantic), `get_bblock`/`get_bblocks`/`list_bblocks_tool` (`get_bblocks` batches full detail for several ids
in one call — batched dependency-edge queries under the hood, not a loop over `get_bblock` — prefer it over looping
`get_bblock` when hydrating a search shortlist), `get_register`/`list_registers_tool`, `get_org`/`list_orgs_tool`,
`bblock_dependencies`/`register_dependencies` (multi-hop graph traversal, either direction).

To point a local Claude Code session at it for manual testing: start the server as above, then
`claude mcp add --transport http bblocks-meta-register http://localhost:8000/mcp` — tools then show up as
`mcp__bblocks-meta-register__*`. Automated tests live in `backend/tests/test_mcp_server.py` (monkeypatches
`session_scope`/`get_embedding_provider` the same way `api_client` overrides the REST API's FastAPI dependencies).

`mcp_allowed_hosts`/`mcp_allowed_origins` (`app/config.py`) gate the MCP endpoint's DNS-rebinding protection and
are deliberately left unset by default — unlike `admin_api_key`, this is *not* a must-set-before-prod flag. DNS
rebinding only matters when a server sits behind a trust boundary (localhost/internal-only) that a browser can
still reach; this API is deliberately public and unauthenticated (same reasoning as the CORS `allow_origins=["*"]`
in `app/main.py`), so there's no session/auth boundary for a rebinding attack to exploit. See the comment in
`app/config.py` for the full reasoning if this ever needs revisiting.