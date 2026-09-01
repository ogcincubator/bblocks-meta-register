# Semantic Binding Lookup — Implementation Plan

**Status: built.** The table, crawler population, repository query function, `GET /bblocks/by-uri` API endpoint,
and `find_bblocks_by_semantic_binding` MCP tool described below are all implemented and tested — see
[04-backend-implementation-status.md](04-backend-implementation-status.md) for the current summary. This document
is kept as the design record (including two query-strategy revisions made *during* implementation — see
"Prefix-match query strategy" below) rather than rewritten into a pure retrospective; sections below describing
something as a plan/proposal reflect what was decided, not what's still outstanding. The one piece explicitly out
of scope here, ontology-term boosting, is still not built — see "Relationship to ontology-term boosting" below.

It answers a gap identified while discussing the MCP/API
surface: there is currently no way to ask "which bblocks bind a schema property to *this* RDF/ontology URI (or to
*any* term under this vocabulary namespace)?" — only a fuzzy chance of it surfacing via `search_bblocks`'s free-text
hybrid search. See [03-indexing-and-search.md](03-indexing-and-search.md)'s "Ontology-term indexing and boosting"
section and [04-backend-implementation-status.md](04-backend-implementation-status.md)'s "What's deferred" — doc 03
already designed a `bblock_uris` reverse-index table of `(bblock_id, uri)` pairs for this exact purpose, but doc 04
confirms it was never built (prior to this plan). This plan:

1. Builds that table (unblocking doc 03's ontology-boost feature later, though that boost pass itself stays
   out of scope here — see "Relationship to ontology-term boosting" below).
2. Corrects doc 03's stated source for it — raw JSON-LD `@context` term values, not `resolvedProperties.json` — in
   light of a precision problem found while researching this (see next section).
3. Adds a new query primitive (repository function + API endpoint + MCP tool) for exact and prefix URI lookup,
   which doc 03 never called for at all (it only used the table internally for score-boosting).

## Terminology note

The rest of this repo, and doc 03, call this a "URI" / `bblock_uris`. The user-facing framing in conversation was
"semantic binding" (a schema property's JSON-LD mapping to an RDF predicate/vocabulary term — see the
`bblocks-authoring` skill's "Semantic annotation" design pattern). Both names refer to the same thing. Code/table
names below stay consistent with the existing `bblock_uris` naming doc 03 already chose; user-facing
docstrings/descriptions use "semantic binding" since that's the more meaningful term to someone who didn't write
the crawler.

## Why `resolvedProperties.json`, not the raw JSON-LD `@context`

Two candidate sources were considered for populating `bblock_uris`:

1. **The bblock's `ldContext` document** (already fetched by `app/search/chunking.py`'s `_ld_context_fields()` for
   the `bblock_schema` search chunk) — its `@context` object maps short field names to either a raw string or an
   `{"@id": ...}` object.
2. **`resolvedProperties.json`** — an internal, *undocumented* output of `bblocks-postprocess-action`
   (`ogc/bblocks/util.py`'s `write_jsonld_context()`, via `ogc.na.annotate_schema.ContextBuilder`/`ResolvedProperty`
   in the `ogc-na-tools` repo), linked from `register.json`'s per-bblock `resolvedSchemaProperties` field when
   present. `chunking.py` already fetches it today, but only as a text fallback for the `bblock_schema` chunk when
   `ldContext` is absent (`_resolved_properties_text()` — property *paths* only, explicitly no URIs, per its own
   docstring).

**Problem with source 1**: a `@context` term's value can be a **compact IRI** (CURIE), e.g. `"sosa:observedProperty"`,
not necessarily a fully-expanded absolute URI. `_ld_context_fields()` reads the context verbatim with no CURIE
expansion. Exact-match lookup against a full URI the caller supplies (e.g.
`http://www.w3.org/ns/sosa/observedProperty`) would silently miss any bblock whose context happens to store the
compact form instead — a correctness gap that would make "exact match" quietly wrong for who-knows-how-many bblocks,
with no way for a caller to tell.

**Why source 2 doesn't have this problem**: confirmed by reading `ogc-na-tools/ogc/na/annotate_schema.py` —
`resolve_context()` runs with `expand_uris=True` by default, and `bblocks-postprocess-action` never overrides it.
Its `expand_uri()` helper (line ~479) expands `prefix:local` against the context's prefix declarations *before* the
value is ever attached to a `ResolvedProperty`. So `ResolvedProperty.id` (and the computed `effective_id` — see
below) is expected to always be a fully-expanded absolute URI by the time it's serialized to
`resolvedProperties.json`. This makes it the correct source for exact/prefix matching; the raw `ldContext` document
stays exactly as-is for its current, unrelated job (free-text embedding fodder in the `bblock_schema` chunk, where
an unexpanded CURIE is a harmless minor loss of recall, not a wrong "no match" claim).

This is also why implementing this plan means editing doc 03's "populate `bblock_uris` from the JSON-LD context's
field→URI mappings" line (Indexing pipeline, step 3) to say `resolvedProperties.json` instead — see "Docs to
update" below.

## `resolvedProperties.json` format (reference)

Not documented anywhere upstream (confirmed with the user) — this section exists so a future reader doesn't have to
re-derive it from `ogc-na-tools` source again.

Fetched from `register.json`'s per-bblock `resolvedSchemaProperties` URL (only present when the block has semantic
annotations to resolve). Shape:

```json
{
  "defs": {
    "3": [ { "path": ["lat"], "id": null, "vocab": "http://www.w3.org/2003/01/geo/wgs84_pos#", "effectiveId": "http://www.w3.org/2003/01/geo/wgs84_pos#lat", "schema_type": "number", "required": true, "sources": ["bblocks://..."] } ]
  },
  "properties": [
    { "path": ["myProp"], "id": "http://example.org/myModel/myProp", "effectiveId": "http://example.org/myModel/myProp", "required": true, "schema_type": "string", "sources": ["bblocks://ogc.bbr.examples.feature.propertySet"] },
    { "path": ["location"], "ref": "3", "schema_type": "object" }
  ]
}
```

Fields, from `ResolvedProperty` (`ogc-na-tools/ogc/na/annotate_schema.py:185-215`) as serialized by
`write_jsonld_context()` (`bblocks-postprocess-action/ogc/bblocks/util.py:242-274`):

| Field | Meaning |
|---|---|
| `path` | JSON path segments to this property (list of strings/indices) |
| `id` | Explicit `x-jsonld-id`/`@id`, if the author set one |
| `vocab` | Active `@vocab` at this point in the schema, if any |
| `effectiveId` | **Computed, already in the JSON**: `id` if set, else `vocab + path[-1]`. This is the URI to index. Omitted from the JSON entirely when null (see `_serialize_rp`'s `v is not None` filter) — absence means "no semantic binding for this property," not a parsing failure. |
| `schema_type`, `required`, `format`, `enum`, `const`, `deprecated`, `read_only`, `write_only` | Schema-level metadata, not needed for this feature |
| `sources` | Which bblock(s) (`bblocks://...`) contributed this binding — provenance, e.g. for a property inherited via `$ref`/import |
| `ref` | If set, this property's own subtree was deduplicated into `defs[ref]` (see below) rather than inlined |

**`ref`/`defs` deduplication**: when the same sub-schema shape recurs at multiple points (e.g. two properties both
`$ref` the same shared type), `ContextBuilder._dedup_to_defs()` hoists the *first* occurrence's descendant
properties into `defs[cache_key]` (as a flat list, each entry's `path` **relative to the referencing property**, not
the document root) and sets `.ref = cache_key` on every property that points at that shape.

**Extraction algorithm for this plan**: we do **not** need to walk `ref` pointers or reconstruct absolute paths.
Every `defs` group only ever exists because at least one `properties` entry (or another `defs` entry) points at it —
so the **union of every `effectiveId` found anywhere in `properties[]` and in every list under `defs{}.values()`**
already covers all bindings in the file, with no risk of missing one. Sketch (illustrative, not final code):

```python
def _resolved_property_bindings(resolved_properties_json: dict) -> list[tuple[str, str]]:
    """(path, uri) pairs for every resolved property with a semantic binding. `path` for a
    defs-derived entry is relative to whatever property referenced that def, not the document
    root — acceptable here since only `uri` drives the lookup this feature adds; `path` is
    carried along purely for eyeballing/debugging, not resolved to be absolute."""
    def _entries(items):
        for item in items:
            uri = item.get("effectiveId")
            path = item.get("path")
            if uri and isinstance(path, list):
                yield (".".join(str(s) for s in path), uri)

    pairs = list(_entries(resolved_properties_json.get("properties") or []))
    for group in (resolved_properties_json.get("defs") or {}).values():
        pairs.extend(_entries(group))
    return list(dict.fromkeys(pairs))  # de-dup identical (path, uri) pairs, preserve order
```

**Coverage caveat**: same population as today's `has_ld_context` roughly, gated by
`resolvedSchemaProperties` being present at all — which itself requires `ctx_builder.resolved_properties` to be
non-empty at generation time (`util.py:243`). A bblock with no semantic annotations anywhere simply has no
`resolvedSchemaProperties` field and contributes zero rows; not an error case, nothing to fall back to.

## Data model

New Core table (same style as `bblock_deps`/`identifier_conflicts` in `app/db/tables.py` — not an ORM model, since
there's no need for `relationship()` traversal, just insert/query):

```python
bblock_uris = Table(
    "bblock_uris",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("bblock_id", ForeignKey("bblocks.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("uri", String, nullable=False, index=True),
    Column("path", JSON, nullable=True),  # list[str], best-effort (see extraction algorithm above)
)
```

`ondelete="CASCADE"` on `bblock_id` mirrors `bblock_deps.source_id`: when `delete_bblocks_for_register()`
(`app/repositories/bblocks.py`) wipes a register's old bblock rows at the top of `index_register()`'s full-replace,
old `bblock_uris` rows for that register are cascade-deleted for free — no separate
"`delete_bblock_uris_for_register`" step needed, same reasoning that already lets `replace_bblock_deps`'s own
per-bblock delete be effectively redundant-but-harmless after a fresh `delete_bblocks_for_register`.

**Migration**: new Alembic revision `0005_bblock_uris.py` (`op.create_table`, matching `0002`'s style — this is a
brand-new table, not a column add, so no FTS5-style drop/recreate dance like `0004` needed).

**`INDEXER_VERSION` bump required** (`app/crawler/change_detection.py`, currently `2` → `3`): even though this
change lives in `chunking.py` (search-content indexing), not `indexer.py`'s relational extraction functions, the
CLAUDE.md-documented bump rule still applies — `needs_reindex()` is the single gate for a register's *entire*
per-register pipeline (`index_register` **and** `build_search_content`/`write_search_content` together, per
`orchestrator.py`'s `_crawl_one_register`), not just the relational half. Skipping the bump would leave every
already-crawled register's `bblock_uris` permanently empty until its upstream `register.json` `modified` timestamp
happens to change for an unrelated reason.

### Prefix-match query strategy

- **Exact**: `WHERE uri = :uri` — trivial index hit on either SQLite (current) or a hypothetical future Postgres.
- **Prefix** ("everything under this vocabulary namespace", e.g. `http://www.w3.org/ns/sosa/`): went through two
  revisions before landing on the boundary-anchored form actually implemented in
  `app/repositories/bblock_uris.py`'s `_prefix_conditions()`:

  1. This plan originally proposed `LIKE 'prefix%'` on the assumption SQLite's query planner would use a B-tree
     index for it automatically. **Checked with `EXPLAIN QUERY PLAN` (as this plan already said to do), and wrong
     in this codebase**: SQLite only used the `uri` index for the `LIKE` form once `PRAGMA case_sensitive_like=ON`
     was set — which `app/db/base.py` doesn't set (its default, case-insensitive `LIKE` can't safely use a
     `BINARY`-collation index range scan). Without that pragma, `EXPLAIN QUERY PLAN` reported a full
     `SCAN bblock_uris` regardless of row count or an `ANALYZE` pass. Setting the pragma globally was rejected —
     it would silently flip case-sensitivity for any *other* `LIKE` query added later, for a change only this one
     query needs. Replaced with a plain `WHERE uri >= :prefix AND uri < :prefix_upper` range scan (`:prefix_upper`
     = `:prefix` with its last character's code point incremented by one), which needs no pragma.
  2. That plain range scan was then found to have a **correctness bug**, not just a performance one: it matches on
     raw string prefix, not on a namespace/segment boundary, so a query for prefix `http://example.org/ns/a` would
     also match `http://example.org/ns/abc` — a sibling term that merely starts with the same characters, not a
     member of the `.../ns/a` namespace at all. Fixed by anchoring the range to a `/` or `#` boundary: a row only
     counts as a prefix match if its `uri` *is* the (trailing-`/`-or-`#`-stripped) input itself, or continues
     immediately after a `/` or `#` right after it — three conditions (`uri == prefix`, a `/`-bounded range, a
     `#`-bounded range) OR'd together, still on the same `uri` column. Verified via `EXPLAIN QUERY PLAN` that
     SQLite still resolves this via its "OR optimization" (`MULTI-INDEX OR` in the plan output — one index `SEARCH`
     per branch), not a scan. See `_prefix_conditions()`'s docstring in `app/repositories/bblock_uris.py` for the
     `>=`/`<` bound derivation, and `test_find_bblocks_by_uri_prefix_is_boundary_anchored` /
     `test_find_bblocks_by_uri_prefix_query_uses_index` in `backend/tests/test_repositories.py` for both checks.

  A materialized table of precomputed segment-boundary prefixes (one row per `/`-or-`#`-delimited cut of each
  `uri`, turning every prefix query into a plain equality lookup) was considered as a third alternative and
  rejected for now — strictly more portable in principle, but a real schema/crawler change (new table or column,
  segment-splitting extraction logic, another migration) for a correctness/portability gain the boundary-anchored
  range conditions already deliver without one.
- A minimum prefix length is worth enforcing at the API/MCP layer (e.g. reject or warn below ~8 characters) so a
  caller can't accidentally trigger a near-full-table scan with a prefix like `"http:"`. Exact threshold is a
  decision to make during implementation, not fixed here.

### Result ordering

`find_bblocks_by_uri` needs an explicit `ORDER BY` — without one, row order for a `LIMIT`/`OFFSET` query is
whatever the planner happens to produce (incidentally uri-lexical here since that's the index order, but not
guaranteed, and not exact-before-prefix). Two problems that fixes:

1. With `mode="both"` against a namespace that has many prefix matches, a caller's `limit` could get filled
   entirely with prefix hits, pushing the (usually more relevant) exact hits off the page.
2. Without a deterministic order, repeated calls with the same `offset`/`limit` aren't guaranteed to return
   stable pages, especially across writes between calls.

Order: plain `ORDER BY uri, bblock_id` — no special-cased "exact first" expression needed, because of an
invariant of the WHERE clause: every row matching only the boundary-anchored prefix condition necessarily has
`uri` as a strict, longer extension of the input `uri` string (that's what "continues after a `/` or `#` right
after `:uri`" means), and under `BINARY` collation a string always sorts *after* any of its own strict prefixes
(e.g. `"http://ex/ns/" < "http://ex/ns/x"`). So every exact match (`uri == :uri`) already sorts ahead of every
prefix-only match for free, with plain lexical `uri` order and no `CASE` expression — which also means the
`ORDER BY` can reuse the same `uri` index as the `WHERE`'s prefix search instead of forcing a separate sort step.
`bblock_id` is a tiebreaker for determinism among rows with equal `uri`. A row's `match_type` in the result is
always based on actual `uri == :uri` equality, regardless of which `mode` was requested — e.g. a `mode="prefix"`
query still labels a row that happens to equal the input value `"exact"` rather than `"prefix"`, since
`match_type` describes what the row *is*, not what filter admitted it.

## Crawler changes (`app/search/chunking.py`)

Today, `resolvedSchemaProperties` is only fetched *conditionally*, inside the `if not schema_text:` branch — i.e.
only when `ldContext` was absent or failed to produce text. That's no longer sufficient: this feature needs
`resolvedSchemaProperties` fetched **whenever `register.json` has it**, regardless of whether `ldContext` already
produced a usable `schema_text`, since it's now the source of truth for `effectiveId`s even for bblocks that also
have a perfectly good `ldContext`. Restructure the relevant block in `build_register_chunks()`:

```python
resolved_json: dict | None = None
resolved_url = raw_bblock.get("resolvedSchemaProperties")
if resolved_url:
    try:
        fetched = await get_json(client, resolved_url)
    except Exception as exc:  # noqa: BLE001 - best-effort, same as today
        logger.warning("Failed to fetch resolvedSchemaProperties for %s from %s: %s", bblock_id, resolved_url, exc)
    else:
        if isinstance(fetched, dict):
            resolved_json = fetched

schema_text = _bblock_schema_text(ld_context_json) if ld_context_json else ""
if not schema_text and resolved_json:
    schema_text = _resolved_properties_text(resolved_json)  # unchanged fallback behavior

bindings = _resolved_property_bindings(resolved_json) if resolved_json else []
```

Other changes in this file:

- New `_resolved_property_bindings()` (sketched above).
- `build_register_chunks()`'s return type grows a fourth element: `bblock_id -> list[tuple[str, str]]` (path, uri
  pairs) — callers (`build_search_content()` in `app/crawler/indexer.py`, and its caller in
  `app/crawler/orchestrator.py`'s `_crawl_one_register`) need their tuple-unpacking updated accordingly.
- Module docstring (lines 1-23) needs its "`ldContext` and `resolvedSchemaProperties`... only feed the
  `bblock_schema` chunk" claim corrected — `resolvedSchemaProperties` now also feeds `bblock_uris`.

`write_search_content()` (`app/crawler/indexer.py`) gains a `bindings` parameter and, inside its existing per-bblock
loop (the one that already calls `keyword_index.upsert(...)` for each `accepted_bblocks` entry), adds:

```python
await bblock_uris_repo.replace_bblock_uris(session, bblock_id, bindings.get(bblock_id, []))
```

## Repository layer

New file `app/repositories/bblock_uris.py` (mirrors the per-table-concern split already used by
`app/repositories/deps.py`/`bblocks.py`/`registers.py`):

```python
async def replace_bblock_uris(session: AsyncSession, bblock_id: str, bindings: list[tuple[str, str]]) -> None:
    """(path, uri) pairs. Mirrors replace_bblock_deps()'s delete-then-insert shape."""
    await session.flush()
    await session.execute(delete(bblock_uris).where(bblock_uris.c.bblock_id == bblock_id))
    if bindings:
        await session.execute(
            insert(bblock_uris),
            [{"bblock_id": bblock_id, "path": path, "uri": uri} for path, uri in bindings],
        )


async def find_bblocks_by_uri(
    session: AsyncSession,
    uri: str,
    *,
    mode: Literal["exact", "prefix", "both"] = "both",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[UriMatch], int]:  # (page of matches, total matching count)
    ...
```

`find_bblocks_by_uri` returns **both exact and prefix hits distinctly tagged** by `match_type` when `mode="both"`
(the default) — see next section for why the ranking/merging decision is deliberately left to the caller rather
than baked in here. It also returns a total matching count alongside the page, same `(items, total)` shape as
`app.repositories.bblocks.list_bblocks`, so the API layer can populate `BblockListResponse`'s
`numberMatched`/`numberReturned` distinction the same way every other bblock-listing endpoint does — without it, a
caller has no way to tell "these are all the matches" from "there are more beyond `limit`".

## API and MCP surface

Per the user's framing: this is a genuinely different query shape from `search_bblocks`'s hybrid keyword+semantic
search (categorical exact/prefix match on a structured URI value, not fuzzy relevance ranking over free text), so
it gets its **own** endpoint/tool rather than becoming another parameter on `search_bblocks`/`GET /bblocks?q=`. The
tool returns exact and prefix hits as separate, labeled groups (`match_type`); it does **not** compute a merged
numeric score across the two — a caller (an LLM agent via MCP, or the frontend) is free to prefer exact hits,
fall back to prefix hits, or merge both, and different callers will reasonably want different behavior. Baking one
fixed merge policy in here would take that choice away for no clear benefit; doc 03's ontology-boost pass (still
deferred, see below) is the one place a numeric composition already has a defined formula, and this feature isn't
part of that pass.

- **API**: `GET /bblocks/by-uri?uri=<value>&mode=exact|prefix|both&limit=&offset=` — returns bblock summaries
  (same `BblockSummary` shape used elsewhere) each annotated with the matching `uri`/`path`/`match_type`, analogous
  to how search results already carry `matched_chunk_types` (`app/schemas/bblock.py`). A bblock matching more than
  one binding appears once per distinct match (matches `search_bblocks`'s established shape rather than
  introducing a new nesting convention).
- **MCP**: new tool in `app/mcp/server.py`, e.g. `find_bblocks_by_semantic_binding(uri: str, mode: Literal["exact",
  "prefix", "both"] = "both", limit: int = 20)` — docstring should tell the agent explicitly when to prefer this
  over `search_bblocks` (a known vocabulary/term URI or namespace in hand) vs. when free-text search is the right
  tool (a natural-language description of what's needed). The FastMCP server's top-level `instructions` string
  (currently describing `search_bblocks`/`get_bblock`/etc.) should get a line added for it, matching the existing
  style.

Exact endpoint/tool naming (`by-uri` vs `by-semantic-binding`, `find_bblocks_by_uri` vs
`find_bblocks_by_semantic_binding`) is a decision to confirm during implementation, not fixed by this plan — see
"Open questions."

## Relationship to ontology-term boosting (still out of scope)

Doc 03's "Ontology-term indexing and boosting" section describes a *separate* feature that would also consume
`bblock_uris`: embedding external ontology terms (`skos:prefLabel`/`rdfs:label` + definitions) so a natural-language
query phrased in domain vocabulary can match a bblock via its semantic bindings even when the bblock's own prose
never uses those words. That still requires the `ontologies` table, term-embedding pipeline, and boost-scoring pass
described there — none of which this plan builds. This plan only builds the `bblock_uris` table itself and a
direct/explicit lookup on top of it (the caller already has a URI in hand); doc 03's feature is about *discovering*
a relevant URI from free text in the first place. Building `bblock_uris` now is a (welcome) prerequisite for that
later work, not a substitute for it.

## Testing plan

Following existing test module conventions:

- `backend/tests/test_crawler_indexer.py` (or a new `test_chunking.py` if one doesn't already cover
  `chunking.py`'s pure functions) — unit tests for `_resolved_property_bindings()`: properties-only case,
  `defs`-derived case (confirm both are collected), missing/null `effectiveId` (skipped, not an error), duplicate
  `(path, uri)` pairs (de-duplicated).
- `backend/tests/test_repositories.py` — `replace_bblock_uris()` round-trip; `find_bblocks_by_uri()` for all three
  `mode` values; cascade delete when a register's bblocks are wiped via `delete_bblocks_for_register()`; the
  `EXPLAIN QUERY PLAN` index-usage check for the prefix-match query mentioned above.
- `backend/tests/test_api_endpoints.py` — `GET /bblocks/by-uri` happy path, empty-result, `mode` filtering.
- `backend/tests/test_mcp_server.py` — the new tool, following the existing monkeypatch pattern for
  `session_scope`/`get_embedding_provider`.
- `backend/tests/test_search.py` is hybrid-search-specific (FTS5 + `sqlite-vec`) and shouldn't need changes, since
  this feature deliberately stays outside `hybrid_search()` (see previous section).

## Docs updated (done)

- **Doc 03** (`03-indexing-and-search.md`): "populate `bblock_uris`..." (Indexing pipeline, step 3, and the "Data
  model additions" bullet) now names `resolvedProperties.json` and links back here for the detailed
  format/extraction notes.
- **Doc 04** (`04-backend-implementation-status.md`): `bblock_uris` moved out of "What's deferred" (the table,
  crawler population, and direct lookup are done; ontology-term boosting itself is still listed as deferred), and
  the new endpoint/MCP tool are in "What's implemented" (tool count corrected to eleven — the prior "nine" had
  already missed `get_bblocks`, independent of this plan).
- **Doc 02** (`02-viewer-application.md`): "MCP interface" section gained a "Semantic binding lookup" bullet
  alongside "Use-case search" (it describes capability categories, not tool names, so no rename was needed there).

## Decisions made during implementation

(Originally "Open questions (decide during implementation, not here)" — resolved as follows.)

- **Endpoint/tool naming**: `GET /bblocks/by-uri` and `find_bblocks_by_semantic_binding` (repository function
  stayed `find_bblocks_by_uri`).
- **Minimum prefix length**: 8 characters (`MIN_PREFIX_LENGTH` in `app/repositories/bblock_uris.py`), enforced at
  the API/MCP layer as a 422/`ValueError`, not in the repository function itself.
- **`path` field**: exposed as-is in the API/MCP response (`matched_path`), with a doc comment noting it's
  best-effort/relative for `defs`-derived entries.
- **Migration revision number**: `0005` was correct — no other migration landed first.
- **Prefix-match query strategy**: went through two more revisions than planned, both driven by actually checking
  `EXPLAIN QUERY PLAN` instead of trusting a claim — see "Prefix-match query strategy" above for the full story
  (short version: `LIKE 'prefix%'` doesn't use the index without a pragma this codebase doesn't set, and a naive
  `>=`/`<` range scan has a false-positive bug that boundary-anchoring fixes).

## Example-derived bindings (built, addendum)

**Status: built** (migration `0006`, `INDEXER_VERSION` 3 → 4). `bblock_uris` originally had exactly one source:
`resolvedSchemaProperties`'s `effectiveId`s, i.e. bindings the bblock's author *declared* on a schema property.
This addendum adds a second, lower-confidence source: RDF/vocabulary terms a bblock's own **examples** happen to
*use*, scraped from each example's Turtle (`.ttl`) snippet.

**Why Turtle, and why it's cheaper than it looks**: a `.ttl` example snippet is already inlined as `code` text
inside the same `documentation['json-full']` document `chunking.py` fetches for every bblock (`examples[].snippets[]`
with `language: "ttl"`/`"turtle"`) — no second network fetch needed, unlike a naive reading of "scrape RDF examples"
might suggest. Turtle also sidesteps the exact problem that ruled out the raw JSON-LD `@context` as a source for
declared bindings (see "Why resolvedProperties.json, not the raw JSON-LD @context" above): a `.ttl` snippet's
`@prefix` declarations are self-contained, mandatory syntax, so `rdflib` yields fully-expanded predicate/type URIs
directly, no CURIE-expansion step of our own needed.

**Extraction** (`app/search/chunking.py`'s `_turtle_predicate_uris()`/`_example_bindings()`): for each example, parse
its `ttl`/`turtle` snippet (if any) with `rdflib.Graph().parse(data=code, format="turtle")`, then collect every
triple's **predicate** URI plus, separately, the **object** of any `rdf:type` triple (a class IRI — a vocabulary
term too, just not a predicate; e.g. `ex:obs1 a sosa:Observation` should surface `sosa:Observation` alongside
`sosa:observedProperty`). A malformed snippet is logged and skipped, not fatal to the rest of the bblock — matches
this module's existing best-effort handling of `ldContext`/`resolvedSchemaProperties` fetch failures.

**Noise filtering**: predicates/type-objects under a placeholder namespace (`example.org`/`.com`/`.net`/`.edu`,
matching the RFC 2606 reserved domains and the ubiquitous `http://example.org/...` convention bblock examples
routinely use for illustrative subject/object IRIs) are dropped — a caller querying `bblock_uris` for a genuine
vocabulary term would never search for `example.org`, so keeping these would only add lookup noise, not recall. A
predicate position in Turtle is always a full IRI, never a blank node or literal, so no separate blank-node filter
is needed for predicates; `rdf:type`'s object is filtered the same placeholder-aware way since it's semantically a
class IRI, not arbitrary triple data, but is otherwise not filtered by node type (only checked to be a `URIRef` at
all, since an `rdf:type` object could in principle be a blank node in Turtle, which isn't a vocabulary term).

**Provenance and ranking**: an example-derived row's `path` is `"example:<title>"` (or `"example:<index>"` for an
untitled example) rather than a schema property path — a Turtle triple has no notion of "the JSON Schema property
this came from". More importantly, "the bblock's sample data happens to use this term" is weaker evidence than "the
bblock's author declared this binding", so `bblock_uris` gained a `source` column (`"schema"` | `"example"`,
migration `0006`, `server_default="schema"` so pre-existing rows backfill correctly once `INDEXER_VERSION`'s bump
forces a full reindex) used as a ranking tiebreaker in `find_bblocks_by_uri`: results are ordered
`(uri = :uri) DESC, (source = 'schema') DESC, uri, bblock_id` — exact-before-prefix first (kept as an explicit
`CASE` now that a second key exists, rather than relying on the lexicographic-ordering side effect the single-key
version exploited — see `find_bblocks_by_uri`'s docstring), then declared-before-example-only among ties. A caller
asking "which bblocks bind this URI" sees the ones that actually declare the binding before the ones that merely
demonstrate the term in a sample. `matched_source` is exposed alongside `matched_uri`/`matched_path`/`match_type`
on both `GET /bblocks/by-uri` and `find_bblocks_by_semantic_binding`.

**Rejected alternative**: a regex-based `@prefix`/triple scraper, to avoid adding `rdflib` as a dependency. Turtle's
grammar (multi-line literals, nested blank-node syntax, `a` as a keyword synonym for `rdf:type`, base-relative
IRIs, ...) has enough edge cases that a real parser earns its keep here; `rdflib` was added to
`pyproject.toml` instead.

## Ontology-derived bindings (built, addendum)

**Status: built** (`INDEXER_VERSION` 4 → 5, no migration needed — `bblock_uris.source` is a plain `String`, not a
DB-level enum, so a third value needs no schema change). `bblock_uris` gains a third, *highest*-confidence source:
RDF/vocabulary terms a bblock's own `ontology` file **defines**, as opposed to a term it merely *declares a
binding to* (`resolvedSchemaProperties`, `source="schema"`) or *uses* in sample data (a Turtle example,
`source="example"`). An `ontology` file (`bblocks-authoring`'s "Ontology declaration": `ontology.ttl`/`ontology.owl`,
auto-detected if `ontology` isn't set explicitly) is where a bblock is the *authoritative source* of a term, not
just a consumer of one — strictly stronger evidence than either existing source, hence the new top tier.

**Source of the URL**: unlike `resolvedSchemaProperties`/`ldContext`, `register.json`'s per-bblock entry carries
the resolved `ontology` URL directly (`raw_bblock.get("ontology")` — see `bblocks-consuming`'s register.json field
reference) — no per-bblock `json-full` lookup needed to find it, and no extra request beyond the one fetch to pull
the file itself. That file isn't JSON, so it's fetched with a new `app/crawler/http.get_text()` (returns
`(body, Content-Type header)`) rather than `get_json()`.

**Format**: an ontology file is Turtle *or* RDF/XML (`.owl`), unlike an example's always-Turtle-tagged inline
snippet, so `chunking._ontology_format()` picks the `rdflib` parser format from the URL's file extension first
(`.ttl` → turtle, `.owl`/`.rdf` → xml), falling back to sniffing the `Content-Type` header, defaulting to turtle
if neither is conclusive — matching the postprocessor's own auto-detection default.

**Extraction — subjects, not predicates**: this is the mirror image of the example-derived extraction.
`chunking._turtle_predicate_uris()` collects an example's *predicates* (plus `rdf:type` objects), because an
example's *subjects* are throwaway instance IRIs (`ex:obs1`) and its predicates are the interesting vocabulary
terms. An *ontology* file inverts that: its predicates (`rdf:type`, `rdfs:label`, `owl:equivalentClass`,
`rdfs:subClassOf`, ...) are near-universally borrowed from well-known vocabularies and say nothing distinctive
about this bblock, while its **subjects** (`<uri> a owl:Class`, `<uri> a owl:ObjectProperty`, ...) are the terms
it actually mints. So `chunking._ontology_subject_uris()` collects every triple's subject, restricted to
`URIRef` (a blank-node subject — e.g. an anonymous OWL restriction — isn't a vocabulary term with a URI of its
own), reusing the same placeholder-namespace filter (`_is_placeholder_uri`) as the example extractor for
consistency, even though an ontology file using `example.org` illustrative IRIs is unlikely in practice. No
`rdf:type`-object special case is needed here (unlike the example extractor) — a class IRI already shows up
directly as a subject in an ontology file, not only as an object.

**Provenance and ranking**: like an example-derived row's `"example:<title>"`, an ontology-derived row's `path` is
the constant `"ontology"` — an ontology-defined term has no schema property or per-example anchor to carry along,
so the label is purely informational. `find_bblocks_by_uri`'s ranking tiebreaker becomes a proper three-tier
`CASE` (`app/repositories/bblock_uris.py`'s `_SOURCE_RANK`: `"ontology"` → 2, `"schema"` → 1, `"example"` → 0)
rather than the two-tier boolean flip the previous addendum introduced, ordered
`(uri = :uri) DESC, source_rank DESC, uri, bblock_id`.

**Filtering by source**: unlike the ranking-only `source` distinction the example addendum introduced,
`find_bblocks_by_uri` (and both the `GET /bblocks/by-uri` and `find_bblocks_by_semantic_binding` surfaces) now
also accept an optional `sources` filter (`tuple[BindingSource, ...] | None`, e.g. `("schema", "example")`) —
prompted by a concrete use case: a caller looking for *schemas* to compose or extend isn't interested in a bblock
that only matches because its ontology happens to define the queried term, with no schema binding to it at all.
Filtered inside the repository query (not left to the caller to post-filter the returned page), so `total` and
pagination stay correct for the filtered set rather than reporting counts that don't match what's actually
returned.