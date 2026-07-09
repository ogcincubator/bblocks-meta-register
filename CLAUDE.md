# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

Early design stage. `backend/` is empty (no code yet). `frontend/` is a freshly scaffolded Nuxt app with no
application logic beyond the default Vuetify CLI template. Read `docs/01-overall-architecture.md` and
`docs/02-viewer-application.md` before making architectural decisions — they describe two related but distinct
pieces of this project (see below), and the indexing/backend approach is explicitly noted as exploratory/TBD.

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

Not yet implemented. Per the architecture doc, the intended responsibilities are: discover registers via the
meta-registry's `index.json`, fetch each register's compiled `register.json` plus underlying bblock sources, detect
changes (ETag/hash/version) to scope reindexing, maintain a dependency graph (register→register, bblock→bblock)
queryable in both directions, and serve a REST/GraphQL API to the frontend. Search is expected to be hybrid
(embeddings for semantic/multilingual queries + conventional keyword filtering/faceting), with relational metadata
in a conventional database separate from the vector store. FastAPI is the intended framework, per the docs, but no
code exists yet to confirm conventions from.