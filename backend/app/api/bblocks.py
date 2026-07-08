from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import EmbeddingProviderDep, SessionDep
from app.repositories.bblocks import get_bblock, get_bblocks_by_ids, list_bblocks
from app.repositories.deps import incoming_bblock_deps, outgoing_bblock_deps
from app.repositories.registers import get_register_url
from app.schemas.bblock import (
    BblockDetail,
    BblockListResponse,
    BblockSummary,
    DependencyGraph,
    DepEdge,
    GraphEdge,
    GraphNode,
)
from app.search.service import hybrid_search
from app.services.dependency_graph import build_bblock_graph

router = APIRouter(prefix="/bblocks", tags=["bblocks"])


@router.get("", response_model=BblockListResponse)
async def list_bblocks_endpoint(
    session: SessionDep,
    embedding_provider: EmbeddingProviderDep,
    q: str | None = None,
    item_class: str | None = None,
    status: str | None = None,
    register: str | None = Query(default=None, description="Register alias, e.g. 'ogc/main'"),
    org: str | None = None,
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    strict: bool = Query(
        default=False,
        description="Keyword-only matching, skipping semantic search entirely. Default (false) "
        "weights semantic search higher since q is often a natural-language use-case description "
        "rather than a curated set of keywords.",
    ),
) -> BblockListResponse:
    if q:
        return await _search_bblocks(
            session,
            embedding_provider,
            q,
            item_class=item_class,
            status=status,
            register=register,
            org=org,
            limit=limit,
            offset=offset,
            strict=strict,
        )

    items, total = await list_bblocks(
        session,
        item_class=item_class,
        status=status,
        register_id=register,
        org_id=org,
        limit=limit,
        offset=offset,
    )
    summaries = [BblockSummary.model_validate(b) for b in items]
    return BblockListResponse(numberMatched=total, numberReturned=len(summaries), items=summaries)


async def _search_bblocks(
    session: SessionDep,
    embedding_provider: EmbeddingProviderDep,
    q: str,
    *,
    item_class: str | None,
    status: str | None,
    register: str | None,
    org: str | None,
    limit: int,
    offset: int,
    strict: bool,
) -> BblockListResponse:
    register_url = await get_register_url(session, register) if register is not None else None

    hits, total = await hybrid_search(
        session,
        embedding_provider,
        q,
        org=org,
        register_id=register,
        register_url=register_url,
        item_class=item_class,
        status=status,
        limit=limit,
        offset=offset,
        strict=strict,
    )

    bblocks_by_id = await get_bblocks_by_ids(session, [hit.bblock_id for hit in hits])
    summaries = []
    for hit in hits:
        bblock = bblocks_by_id.get(hit.bblock_id)
        if bblock is None:
            continue  # search index momentarily ahead of a concurrent relational delete
        summary = BblockSummary.model_validate(bblock)
        summaries.append(summary.model_copy(update={"matched_chunk_types": hit.matched_chunk_types}))

    return BblockListResponse(numberMatched=total, numberReturned=len(summaries), items=summaries)


@router.get("/{identifier}/graph", response_model=DependencyGraph)
async def get_bblock_graph_endpoint(
    identifier: str,
    session: SessionDep,
    direction: Literal["depends_on", "dependents", "both"] = "both",
    depth: int = Query(default=2, ge=1, le=5),
) -> DependencyGraph:
    if await get_bblock(session, identifier) is None:
        raise HTTPException(status_code=404, detail=f"Bblock '{identifier}' not found")

    graph = await build_bblock_graph(session, identifier, direction, depth)
    return DependencyGraph(
        nodes=[GraphNode(**vars(n)) for n in graph.nodes],
        edges=[GraphEdge(**vars(e)) for e in graph.edges],
    )


@router.get("/{identifier}", response_model=BblockDetail)
async def get_bblock_endpoint(identifier: str, session: SessionDep) -> BblockDetail:
    bblock = await get_bblock(session, identifier)
    if bblock is None:
        raise HTTPException(status_code=404, detail=f"Bblock '{identifier}' not found")

    depends_on = [DepEdge(id=t, kind=k) for t, k in await outgoing_bblock_deps(session, identifier)]
    dependents = [DepEdge(id=s, kind=k) for s, k in await incoming_bblock_deps(session, identifier)]

    return BblockDetail(
        **BblockSummary.model_validate(bblock).model_dump(),
        date_time_addition=bblock.date_time_addition,
        date_of_last_change=bblock.date_of_last_change,
        schema_urls=bblock.schema_urls,
        ld_context_url=bblock.ld_context_url,
        shacl_shapes_urls=bblock.shacl_shapes_urls,
        sources=bblock.sources,
        depends_on=depends_on,
        dependents=dependents,
    )
