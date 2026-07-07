from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Bblock, Register


async def list_bblocks(
    session: AsyncSession,
    *,
    item_class: str | None = None,
    status: str | None = None,
    register_id: str | None = None,
    org_id: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Bblock], int]:
    """Returns (page of bblocks, total matching count), ordered by id.

    No `q` param here -- a free-text query is handled by app/search/service.py's hybrid search
    instead (see app/api/bblocks.py), which returns ranked bblock ids that get_bblocks_by_ids()
    below then hydrates. This function is the plain browse/filter path.
    """
    stmt = select(Bblock)
    if org_id is not None:
        stmt = stmt.join(Register, Bblock.register_id == Register.id).where(Register.org_id == org_id)
    if register_id is not None:
        stmt = stmt.where(Bblock.register_id == register_id)
    if item_class is not None:
        stmt = stmt.where(Bblock.item_class == item_class)
    if status is not None:
        stmt = stmt.where(Bblock.status == status)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await session.execute(count_stmt)).scalar_one()

    stmt = stmt.order_by(Bblock.id).limit(limit).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().all()), total


async def get_bblock(session: AsyncSession, bblock_id: str) -> Bblock | None:
    return await session.get(Bblock, bblock_id)


async def get_bblocks_by_ids(session: AsyncSession, ids: list[str]) -> dict[str, Bblock]:
    """Unordered id -> Bblock lookup for hydrating a ranked id list from hybrid search --
    callers apply the ranking, this just avoids N+1 session.get() round trips."""
    if not ids:
        return {}
    result = await session.execute(select(Bblock).where(Bblock.id.in_(ids)))
    return {bblock.id: bblock for bblock in result.scalars().all()}


async def upsert_bblock(
    session: AsyncSession,
    *,
    bblock_id: str,
    register_id: str,
    name: str,
    abstract: str | None,
    status: str | None,
    item_class: str | None,
    version: str | None,
    tags: list[str],
    date_time_addition: str | None,
    date_of_last_change: str | None,
    has_schema: bool,
    has_ld_context: bool,
    has_shacl_shapes: bool,
    schema_urls: dict,
    ld_context_url: str | None,
    shacl_shapes_urls: list[str],
    sources: list[dict],
) -> Bblock:
    bblock = Bblock(
        id=bblock_id,
        register_id=register_id,
        name=name,
        abstract=abstract,
        status=status,
        item_class=item_class,
        version=version,
        tags=tags,
        date_time_addition=date_time_addition,
        date_of_last_change=date_of_last_change,
        has_schema=has_schema,
        has_ld_context=has_ld_context,
        has_shacl_shapes=has_shacl_shapes,
        schema_urls=schema_urls,
        ld_context_url=ld_context_url,
        shacl_shapes_urls=shacl_shapes_urls,
        sources=sources,
    )
    session.add(bblock)
    return bblock


async def delete_bblocks_for_register(session: AsyncSession, register_id: str) -> None:
    await session.execute(delete(Bblock).where(Bblock.register_id == register_id))


async def get_owning_register_id(session: AsyncSession, bblock_id: str) -> str | None:
    result = await session.execute(select(Bblock.register_id).where(Bblock.id == bblock_id))
    return result.scalar_one_or_none()
