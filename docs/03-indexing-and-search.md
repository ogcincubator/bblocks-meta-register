# Indexing & Search Strategy — Architecture Summary

This document fills in the piece both [01-overall-architecture.md](01-overall-architecture.md) and
[02-viewer-application.md](02-viewer-application.md) deferred: how bblocks actually get chunked, embedded, and
ranked at query time. It assumes the storage decisions already made in doc 02 (SQLite for relational metadata,
FTS5 for keyword search, `sqlite-vec` for vector search) and does not reopen them — see
[Vector store](#vector-store-sqlite-vec) below for why that choice still holds at this catalog's scale.

An early prototype (not part of this repo) explored a chunking/embedding/boosting strategy against a different
storage stack (ChromaDB + a local Ollama embedding server). Several ideas from it are carried forward here — the
multi-chunk-per-bblock embedding strategy and ontology-term boosting in particular — adapted to sqlite-vec/FTS5 and
a pluggable embedding provider.

## Vector store: `sqlite-vec`

The catalog this service indexes — bblocks across every register known to the meta-registry — is realistically
hundreds to low thousands of items, not millions. At that scale, `sqlite-vec`'s brute-force cosine scan resolves a
query in single-digit milliseconds; there's no practical need for an approximate-nearest-neighbor index like
Chroma's HNSW or a dedicated vector database. Using `sqlite-vec` also means the vector index lives in the same
SQLite file as the relational metadata and FTS5 tables — one storage engine, one file, no separate DB process to
deploy or keep in sync. Chroma or pgvector would each solve a scale problem this catalog doesn't have, at the cost
of a second operational dependency.

**Escape hatch**: if the corpus grows by orders of magnitude (e.g. every register everywhere gets indexed at full
content granularity, not just bblock-level metadata), swapping `sqlite-vec` for a dedicated vector store is a
contained change — the embedding/chunking logic and the `VectorStore` interface below don't change, only the
implementation behind it.

```python
class VectorStore(Protocol):
    def upsert(self, chunks: list[Chunk]) -> None: ...
    def search(self, embedding: list[float], n: int, where: dict | None = None) -> list[ChunkResult]: ...
    def delete_where(self, where: dict) -> None: ...
```

## Embedding provider interface

No specific embedding provider is committed to. Different deployments may want a self-hosted model (no per-call
cost, no external dependency, but requires running a model server) or a hosted embeddings API (no infrastructure
to run, but an external dependency and per-call cost). Both should be options, selected via configuration —
concretely, an `EmbeddingProvider` interface with two implementations:

```python
class EmbeddingProvider(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...
```

- **`OllamaEmbeddingProvider`** — calls a self-hosted Ollama instance's `/api/embed` endpoint. Good default for
  a self-managed deployment; no external API dependency, data never leaves the deployment.
- **`OpenAICompatibleEmbeddingProvider`** — calls any OpenAI-compatible `/embeddings` endpoint (OpenAI, or any
  hosted provider that implements the same API shape). Good default when running the model locally isn't
  desirable.

Configuration picks the implementation and its connection details (base URL, model name, API key if applicable).
Query-side instruction prefixing (some embedding models perform better when the query is wrapped in a
task-specific instruction string, distinct from how documents are embedded) is a provider-level concern, not
something the indexer or search service needs to know about.

## Chunking strategy

A bblock is not embedded as a single blob — different parts of it answer different kinds of queries, and
embedding them separately lets search surface *why* a bblock matched. Each register, once fetched, produces a
handful of chunk types:

| Chunk type | Source | Content |
|---|---|---|
| `register_summary` | register.json root fields | name, abstract, description — lets a query surface an entire register, not just individual bblocks |
| `bblock_core` | bblock.json fields | name, abstract, tags — short, precise identity text. `itemClass`/`status` are deliberately excluded: both are already exact-match query filters on `hybrid_search`, so embedding them as free text would only add noise |
| `bblock_description` | bblock's `documentation.json-full` doc | the full markdown `description` (absent from register.json) — kept as its own chunk rather than folded into `bblock_core`, so its much longer prose doesn't dilute that chunk's embedding |
| `bblock_schema` | JSON-LD context (`ldContext`) | field names mapped to their semantic URIs — lets a query phrased in vocabulary terms (e.g. "schema:name") match a bblock whose field is called something else entirely |
| `bblock_usage` | bblock.json (`sources`, `transforms`) + `documentation.json-full` doc | sources (specs/papers this block is based on), transform descriptions (conversions it supports), and example titles/content/snippet code — all "how this block relates to other formats/standards" content, capped in length so a large example set doesn't dominate the chunk |

Each chunk carries minimal metadata for filtering at query time — `org`, `register_url`, `bblock_id`, `item_class`,
`chunk_type` — with the display-oriented fields (name, abstract, etc.) kept in the relational metadata tables,
not duplicated into the vector store.

`org` is denormalized into chunk metadata even though it's derivable by joining through the register, and this is
a correctness requirement, not just convenience: a `sqlite-vec` KNN query returns the top-K nearest chunks from
the whole index, and a join applied *after* that can only narrow that already-fixed top-K set. Filtering by org
post-hoc could silently return fewer than K results (or none) even when better-matching chunks for that org exist
further down the unranked index — the true top-K "nearest chunks in org X" is not the same set as "org X members
of the globally nearest K chunks." For the filter to be correct, it has to be a column native to the vector index
itself, applied *during* the nearest-neighbor scan — which is what `sqlite-vec` metadata columns are for. The
general rule: any field callers filter by needs to live in chunk metadata as a "static" filter, not just be
derivable via a join, or filtering + top-K will silently under-fill results.

At query time, the best-scoring chunk per bblock wins, and the *set* of chunk types that matched
(`matched_chunk_types`) is returned alongside the result — useful for the frontend to show *why* a bblock matched
("matched on: schema fields, examples") rather than just a bare score.

## Ontology-term indexing and boosting

Independent of any specific register, external ontologies/vocabularies (SKOS, RDFS) referenced by bblocks' JSON-LD
contexts can be indexed on their own: for each named term (a `skos:prefLabel` or `rdfs:label`, plus its
`skos:definition`/`rdfs:comment` if present), embed a small `ontology_term` chunk keyed by the term's URI.

At search time, in addition to the direct bblock search, the query is also matched against indexed ontology terms.
If a well-matching term's URI is one that some bblock's JSON-LD context actually maps a field to (recorded via a
`bblock_uris` reverse-index table, populated during indexing), that bblock's score gets boosted by a fraction of
the ontology match's score:

```
boosted_score = min(1.0, best_chunk_score + ontology_match_score * ONTOLOGY_BOOST_WEIGHT)
```

This lets a query phrased in domain vocabulary ("a place with a geometry and a name", using terms from a
well-known ontology) surface bblocks that use those exact semantic mappings even if the bblock's own prose never
uses those words. Ontology indexing is a separate, opt-in step from register indexing — the search service should
work with zero ontologies loaded, boosting is a pure enhancement. Ontology term chunks carry no `org`/`register_url`
of their own (a vocabulary isn't scoped to one org or register) — the boost is applied after the org/register
filter has already narrowed the direct bblock search, via the `bblock_uris` join, so a vocabulary term can still
boost a bblock even though the term chunk itself sits outside any org's or register's static filters.

## Hybrid search

Doc 02 already calls for FTS5 (exact identifier/acronym lookups) + `sqlite-vec` (semantic queries) as the hybrid
search approach; this section makes that concrete now that the chunking scheme above exists.

1. **Keyword pass** — FTS5 query over `name`, `abstract`, `description`, `tags`, `itemIdentifier`. Cheap,
   exact-ish matches (identifiers, acronyms, exact tag names) that embeddings are typically weak at; per-column
   `bm25()` weights favor `name` over `abstract` over `description` (see `app/search/keyword_index.py`).
2. **Semantic pass** — embed the query once, search `sqlite-vec` over `bblock_core`, `bblock_description`,
   `bblock_schema`, and `bblock_usage` chunks (`register_summary` chunks are searched separately when the caller
   wants register-level results, e.g. for the `/registers` search surface rather than `/bblocks`). Take the best
   chunk score per bblock.
3. **Ontology boost pass** — as described above, added on top of the semantic pass's score.
4. **Merge and rank** — a bblock that hits in the keyword pass is guaranteed inclusion (keyword matches are strong
   signals FTS5 already found exactly); its rank score is `max(keyword_score, semantic_score + ontology_boost)`.
   Everything else is ranked by `semantic_score + ontology_boost` alone. Final list is truncated to the requested
   page size.

Query-side filters (`item_class`, `register_url`, `org`) apply identically to both passes before merging, not
after — filtering post-merge would mean the top-N cutoff in each pass could discard results that would have
survived filtering.

## Indexing pipeline

Reindexing is scoped per register, matching the change-detection step already described in doc 02: when a
register's content hash changes, that register's data is fully replaced (relational rows, chunks, reverse-index
entries) — not incrementally patched, since bblocks within a register are cheap enough to fully re-chunk and
re-embed on any change, and this avoids tracking per-bblock diffs.

For a single register, per run:

1. Delete existing rows/chunks for the register (`bblocks`, `bblock_uris`, and vector chunks matching
   `register_url`), keyed by register URL — idempotent, safe to re-run.
2. Fetch `register.json`, upsert the register's own relational row, and build+embed its `register_summary` chunk.
3. For each bblock: upsert its relational row; fetch its JSON-LD context (if present) and full JSON content
   (description, examples) as needed; build the `bblock_core`, `bblock_description`, `bblock_schema`,
   `bblock_usage` chunks; populate
   `bblock_uris` from the JSON-LD context's field→URI mappings (also the raw material the dependency graph in
   doc 02 draws on, though that's a distinct edge table keyed on `dependsOn`/`isProfileOf`, not on JSON-LD URIs).
4. Batch-embed all collected chunk texts in one pass (fewer round trips to the embedding provider than
   per-bblock calls) and upsert into `sqlite-vec`.

Ontology indexing is a separate, independently-triggered pipeline (new/changed ontology source → re-parse → embed
terms → upsert), not tied to any register's reindex cycle.

## Data model additions

On top of the relational tables already described in doc 02 (`orgs`, `registers`, `bblocks`,
`bblock_deps`/`register_deps`):

- **`sqlite-vec` virtual table** for chunk embeddings, with columns for the embedding vector plus the filtering
  metadata (`org`, `register_url`, `bblock_id`, `item_class`, `chunk_type`).
- **`bblock_uris`** — reverse index of `(bblock_id, uri)` pairs from JSON-LD context field mappings. Used for
  ontology-boost lookups (find bblocks using a given URI); a separate concern from the `dependsOn`/`isProfileOf`
  dependency edges in doc 02, which come from `bblock.json` metadata directly rather than JSON-LD contexts.
- **`ontologies`** — one row per indexed ontology source (file path or URL), with term count and last-indexed
  timestamp, mirroring the per-register change-detection bookkeeping doc 02 describes.

## Open questions

- **Ontology source list** — where the set of ontologies to index is configured (a static list, or discovered
  from the URIs actually referenced across all indexed JSON-LD contexts) is not yet decided.
- **Chunk size limits for very large examples** — the prototype capped snippet length per chunk; the right cap,
  and whether to split a single large example into multiple chunks instead of truncating, needs revisiting once
  real-world example sizes across registers are surveyed.
- **`ONTOLOGY_BOOST_WEIGHT` tuning** — needs empirical tuning once there's a real corpus and a few evaluation
  queries to check the boost isn't over- or under-weighted relative to direct semantic matches.
