# OGC Building Blocks Meta-Registry

A catalog and search UI across every [OGC Building Blocks](https://github.com/ogcincubator/bblocks-postprocess)
register known to the [OGC Building Blocks meta-registry](https://w3id.org/ogc/bblocks/) — an
organization → register → bblock directory, with reverse-dependency lookup ("what depends on this bblock/register")
that no single register's own viewer can provide on its own.

This is a *catalog*, not a replacement for [bblocks-viewer](https://github.com/ogcincubator/bblocks-viewer) (the
per-register detail renderer): register and bblock pages here are intentionally shallow (metadata, dependency
graph, presence/absence of schema/context/shapes assets) and link out to each register's own hosted viewer for
actual schema/example content.

See [`docs/`](docs/) for the full design:
- [`01-overall-architecture.md`](docs/01-overall-architecture.md) — the meta-registry itself (the `registers.yaml` /
  `index.json` alias directory this app crawls; lives outside this repo)
- [`02-viewer-application.md`](docs/02-viewer-application.md) — this app's architecture (backend + frontend)
- [`03-indexing-and-search.md`](docs/03-indexing-and-search.md) — crawling, change detection, hybrid search design
- [`04-backend-implementation-status.md`](docs/04-backend-implementation-status.md) /
  [`05-frontend-implementation-status.md`](docs/05-frontend-implementation-status.md) — what's actually built vs.
  what the design docs describe

## Structure

```
backend/   FastAPI + SQLAlchemy crawler, data access layer, REST API, and MCP server
frontend/  Nuxt 4 / Vue 3 / Vuetify + Tailwind catalog UI
docs/      Architecture and design documents
```

## Backend

Python 3.12+, [Poetry](https://python-poetry.org/). From `backend/`:

```bash
poetry install
poetry run fastapi dev app/main.py   # dev server, http://localhost:8000
poetry run pytest
poetry run ruff check .
```

Copy `.env.example` to `.env` to override defaults (database path, crawl interval, meta-registry source URLs,
embedding provider, admin API key, etc.) — see that file for the full list. The app self-migrates its SQLite
database on startup.

Exposes:
- REST: `/orgs`, `/registers`, `/bblocks` (hybrid keyword + semantic search via `?q=`), `/admin/*`
- MCP server at `/mcp` (search/browse/detail tools plus dependency-graph traversal), for use by LLM tooling

## Frontend

Node.js, [Yarn](https://yarnpkg.com/). From `frontend/`:

```bash
yarn install
yarn dev       # dev server
yarn build     # production build
yarn lint
```

Points at the backend via `NUXT_PUBLIC_API_BASE` (defaults to `http://localhost:8000`).

## Running with Docker

`docker-compose.prod.yml` runs the full stack (backend, frontend, and a local Ollama instance for embeddings) from
published images. See the comments in that file for required/optional environment variables (`BBLOCKS_ADMIN_API_KEY`
is required; everything else has a sensible default):

```bash
docker compose -f docker-compose.prod.yml up
```

Images are built by the workflows in `.github/workflows/` and published to GHCR on every push to `main`.

## License

Apache License 2.0 — see [`LICENSE`](LICENSE).
