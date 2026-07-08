"""Hybrid search (docs/03-indexing-and-search.md's "Hybrid search" section): a keyword pass
(FTS5, cheap exact-ish matches) and a semantic pass (sqlite-vec, best chunk per bblock),
merged so a bblock hit in the keyword pass is guaranteed inclusion. Ontology-term boosting is
not implemented yet -- doc 03 describes it as a separate, independently-triggered opt-in step,
so semantic_score is used unboosted for now.

Query-side filters (org, register, item_class, status) are applied identically to both passes
*before* merging, per doc 03 -- applying them post-merge would let each pass's own candidate-N
cutoff discard results that would otherwise have survived filtering.

Default (non-strict) merging weights the semantic pass heavily (settings.search_semantic_weight):
real queries here are as often a paragraph-length, possibly non-English description of a use
case as they are a couple of keywords, and only the embedding-based pass actually understands
that kind of input -- the keyword pass's strict per-token AND (see keyword_index._sanitize_query)
just contributes nothing for a query like that, rather than actively hurting it. `strict=True`
(the API's `strict=1`) skips the semantic pass and embedding call entirely, for callers that
want fast, precise, keyword-only matching instead.
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.search import keyword_index, vector_store
from app.search.embeddings import EmbeddingProvider

# The chunk types a direct bblock search considers -- register_summary chunks are deliberately
# excluded here (doc 03: searched separately for register-level results, not /bblocks).
BBLOCK_CHUNK_TYPES = ["bblock_core", "bblock_schema", "bblock_examples"]


@dataclass(frozen=True)
class SearchHit:
    bblock_id: str
    score: float
    matched_chunk_types: list[str]


def _keyword_score(bm25: float) -> float:
    """bm25() is <= 0, more negative meaning a stronger match -- map to a (0, 1) score that
    preserves that ordering so it's comparable to the semantic pass's score."""
    magnitude = max(0.0, -bm25)
    return magnitude / (1.0 + magnitude)


def _semantic_score(distance: float) -> float:
    """Vector table uses cosine distance (0 = identical, 2 = opposite) -- clamp to [0, 1]
    since a merged/ranked score below 0 has no meaningful interpretation here."""
    return max(0.0, 1.0 - distance)


async def hybrid_search(
    session: AsyncSession,
    embedding_provider: EmbeddingProvider,
    query: str,
    *,
    org: str | None = None,
    register_id: str | None = None,
    register_url: str | None = None,
    item_class: str | None = None,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
    strict: bool = False,
) -> tuple[list[SearchHit], int]:
    keyword_hits = await keyword_index.search(
        session,
        query,
        settings.search_keyword_candidates,
        org=org,
        register_id=register_id,
        item_class=item_class,
        status=status,
    )
    keyword_scores = {hit.bblock_id: _keyword_score(hit.score) for hit in keyword_hits}

    if strict:
        merged = [
            SearchHit(bblock_id=bblock_id, score=score, matched_chunk_types=[])
            for bblock_id, score in keyword_scores.items()
        ]
        merged.sort(key=lambda hit: hit.score, reverse=True)
        return merged[offset : offset + limit], len(merged)

    query_embedding = await embedding_provider.embed_query(query)
    semantic_hits = await vector_store.search(
        session,
        query_embedding,
        settings.search_semantic_candidates,
        chunk_types=BBLOCK_CHUNK_TYPES,
        org=org,
        register_url=register_url,
        item_class=item_class,
        status=status,
    )

    # Best (lowest-distance) chunk per bblock wins; matched_chunk_types collects every chunk
    # type that showed up for that bblock among the semantic candidates.
    best_distance: dict[str, float] = {}
    matched_chunk_types: dict[str, set[str]] = {}
    for hit in semantic_hits:
        if hit.bblock_id is None:
            continue
        matched_chunk_types.setdefault(hit.bblock_id, set()).add(hit.chunk_type)
        if hit.bblock_id not in best_distance or hit.distance < best_distance[hit.bblock_id]:
            best_distance[hit.bblock_id] = hit.distance

    semantic_scores = {bblock_id: _semantic_score(distance) for bblock_id, distance in best_distance.items()}

    semantic_weight = settings.search_semantic_weight
    all_bblock_ids = set(keyword_scores) | set(semantic_scores)
    merged = [
        SearchHit(
            bblock_id=bblock_id,
            score=semantic_weight * semantic_scores.get(bblock_id, 0.0)
            + (1 - semantic_weight) * keyword_scores.get(bblock_id, 0.0),
            matched_chunk_types=sorted(matched_chunk_types.get(bblock_id, set())),
        )
        for bblock_id in all_bblock_ids
    ]

    merged.sort(key=lambda hit: hit.score, reverse=True)
    return merged[offset : offset + limit], len(merged)
