from fastapi import APIRouter, HTTPException, Query

from app.api.deps import SessionDep
from app.repositories.bblocks import get_bblock, list_bblocks
from app.repositories.deps import incoming_bblock_deps, outgoing_bblock_deps
from app.schemas.bblock import BblockDetail, BblockListResponse, BblockSummary, DepEdge

router = APIRouter(prefix="/bblocks", tags=["bblocks"])


@router.get("", response_model=BblockListResponse)
async def list_bblocks_endpoint(
    session: SessionDep,
    q: str | None = None,
    item_class: str | None = None,
    register: str | None = Query(default=None, description="Register alias, e.g. 'ogc/main'"),
    org: str | None = None,
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> BblockListResponse:
    items, total = await list_bblocks(
        session,
        q=q,
        item_class=item_class,
        register_id=register,
        org_id=org,
        limit=limit,
        offset=offset,
    )
    summaries = [BblockSummary.model_validate(b) for b in items]
    return BblockListResponse(numberMatched=total, numberReturned=len(summaries), items=summaries)


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
