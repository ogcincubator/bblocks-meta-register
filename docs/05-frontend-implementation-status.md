# Frontend Implementation Status

This document tracks what's actually built in `frontend/` versus what
[02-viewer-application.md](02-viewer-application.md) describes, so a future session doesn't have to re-derive it
from the code. Broad strokes only — read the doc above and the code itself for the rest.

## What's implemented

- **App shell** (`app/app.vue`): a single top `v-app-bar` (title, global search field, link to the org listing,
  theme toggle) wrapping `nuxt-page`. No navigation drawer — the three-level hierarchy (org → register → bblock) is
  navigated via breadcrumbs and in-page links instead, per doc 02's "deliberately minimal" register/bblock views.
- **API layer**: `app/types/api.ts` mirrors the backend's pydantic response schemas by hand (kept in sync manually,
  not generated). `app/composables/useApi.ts` wraps Nuxt's `useFetch` with `runtimeConfig.public.apiBase`
  (`nuxt.config.ts`, overridable via `NUXT_PUBLIC_API_BASE` at runtime) as the base URL.
- **Pages**, all built from stock Vuetify components (`v-card`, `v-list`, `v-chip`, `v-breadcrumbs`,
  `v-skeleton-loader`, etc.) with no custom CSS beyond the Tailwind utility classes already in the scaffold — the
  intent is a "standard" Vuetify look first, visual customization later:
  - `pages/index.vue` — hero search + first 6 orgs.
  - `pages/orgs/index.vue` — full org listing.
  - `pages/orgs/[org].vue` — org metadata, maintainers, list of its registers.
  - `pages/registers/[org]/[register].vue` — register metadata, crawl status (`last_crawled_at`/
    `last_crawl_status`/`modified`), register-level depends-on/dependents chips, bblock listing. No schema/example
    rendering, per doc 02 — links out to `register_url`/`viewer_url` instead.
  - `pages/bblocks/[identifier].vue` — bblock metadata, a row of asset buttons driven by presence/absence
    (`schema_urls`/`ld_context_url`/`shacl_shapes_urls`, all optional), tags, sources, and bblock-level
    depends-on/dependents chips (the reverse-dependency feature doc 02 calls out as differentiating).
  - `pages/search.vue` — the Records-inspired `GET /bblocks?q=` endpoint with `item_class`/`status` filters and
    `v-pagination`; query state is synced to the URL so results are shareable/bookmarkable.
- Shared presentational components: `StatusChip.vue` (status → color mapping) and `BblockListItem.vue` (used by
  both the register detail page and search results, so the two listing UIs stay visually identical).
- **Backend CORS**: `backend/app/main.py` now adds `CORSMiddleware` (`allow_origins=["*"]`, GET-only) so the
  frontend can call the API directly in local dev without a proxy — safe given the API is public/read-only by
  design (doc 02).
- **Docker image** (`frontend/Dockerfile`, `frontend/.dockerignore`): multi-stage build — `yarn build` (Node.js SSR
  output, `yarn` install with `--frozen-lockfile`) in a `node:24-alpine` builder stage, then a slim `node:24-alpine`
  runtime stage that just runs `node .output/server/index.mjs`. This is the Node.js SSR option from doc 02's
  deployment section, not `yarn generate` static output — deliberately, since `ssr: false`/static generation would
  reopen the `defaultTheme: 'dark'` hydration-warning problem `nuxt.config.ts` already has a comment about avoiding
  (see the top-level `CLAUDE.md`). `NUXT_PUBLIC_API_BASE` is read from the environment at container start (Nuxt's
  standard `NUXT_PUBLIC_<KEY>` runtime-config override), not baked in at build time — no placeholder/`sed`
  substitution trick is needed the way a static-output image would need one, since a live Node process can just
  read the env var per request and inject it into both the SSR payload and the hydration `<script>` blob. Verified
  by building the image and curling a running container (200 OK, `apiBase` present in the rendered payload).
- **Mobile responsiveness**: app-bar collapses to icon buttons (search/orgs) below `md` instead of cramming a
  search field + text button + title into one row; `BblockListItem.vue` hides its secondary schema/context/shapes
  icons and item-class chip below `sm` (status chip stays) and stacks name/id vertically instead of overflowing;
  `search.vue`'s filter selects go full-width below `sm` instead of squeezing to half-width. All done with plain
  Tailwind responsive classes (`md:flex`, `md:hidden`, `sm:flex-row`, etc.), not JS viewport detection
  (`useDisplay().mobile`) — the latter was tried first and reverted: Vuetify's SSR viewport guess defaults to
  "mobile" for any browser without Client-Hints support (i.e. Firefox/Safari, and any browser on the very first
  request), so it would have server-rendered the mobile layout for most desktop visitors and flipped it right after
  hydration — the same class of hydration-mismatch flash `nuxt.config.ts`'s theme comment already avoids for a
  different reason.
- **Fixed: utility classes were silently no-ops.** `assets/styles/settings.scss` sets `$utilities: false`, which
  (per `CLAUDE.md`) deliberately disables *all* of Vuetify's generated utility classes so Tailwind is the only
  source of layout/spacing/typography utility classes — but this was discovered only after writing every page using
  Vuetify/Bootstrap-convention names (`d-flex`, `ga-2`, `text-h4`, `font-weight-medium`, `text-medium-emphasis`,
  etc.), none of which exist under either framework with `$utilities: false` set. Confirmed by grepping the
  compiled `.output/public/_nuxt/*.css` for these class names (zero matches) with no browser available in-session
  to catch it visually. Swept every `.vue` file under `app/` and replaced with real Tailwind names (`flex`/`hidden`/
  `md:flex`, `gap-2`, `text-3xl`/`text-2xl`/etc., `font-bold`/`font-medium`, `opacity-70` in place of Vuetify's
  medium-emphasis text color, `truncate`, `no-underline`). Re-verified the replacements are present in the compiled
  CSS. See the `frontend-tailwind-utilities-only` memory for the full class-name mapping used.

## What's deferred (not started)

- **Visual identity** — this is intentionally the stock Vuetify theme (default Material-ish look, no brand colors/
  typography/spacing customization yet), per the explicit "standard Vuetify first" direction this was built under.
- **Admin surface** — `/admin/status`, `/admin/registers`, and `/admin/conflicts` (doc 02) have no frontend views;
  only the public browse/search surface is built.
- **Dependency graph visualization** — depends-on/dependents are rendered as flat chip lists, not the "graph" doc
  02 mentions as an option for the register view.
- **No generated API client / OpenAPI sync check** — `types/api.ts` will silently drift if the backend schemas
  change; nothing currently catches that.
- **No frontend tests** — no component/e2e test setup exists yet.
