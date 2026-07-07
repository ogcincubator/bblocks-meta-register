"""Dependency edge queries -- plain Core statements against bblock_deps/register_deps.

No ORM relationship()s here on purpose: both tables allow a dangling target (the target
bblock/register may not be indexed yet, or ever). See app/db/tables.py.
"""

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tables import bblock_deps, register_deps


async def replace_bblock_deps(
    session: AsyncSession, source_id: str, edges: list[tuple[str, str]]
) -> None:
    """Replace all outgoing edges for one bblock. `edges` is a list of (target_id, kind).

    Flushes first: unlike a `select()`, a Core `insert()`/`delete()` executed via
    `session.execute()` does not autoflush pending ORM adds, so a bblock upserted via
    upsert_bblock() just before this call wouldn't be visible yet -- tripping the FK on
    bblock_deps.source_id (see app/db/tables.py) even though the row is "already" added.
    """
    await session.flush()
    await session.execute(delete(bblock_deps).where(bblock_deps.c.source_id == source_id))
    if edges:
        await session.execute(
            insert(bblock_deps),
            [{"source_id": source_id, "target_id": target_id, "kind": kind} for target_id, kind in edges],
        )


async def outgoing_bblock_deps(session: AsyncSession, bblock_id: str) -> list[tuple[str, str]]:
    result = await session.execute(
        select(bblock_deps.c.target_id, bblock_deps.c.kind).where(bblock_deps.c.source_id == bblock_id)
    )
    return [(row.target_id, row.kind) for row in result]


async def incoming_bblock_deps(session: AsyncSession, bblock_id: str) -> list[tuple[str, str]]:
    result = await session.execute(
        select(bblock_deps.c.source_id, bblock_deps.c.kind).where(bblock_deps.c.target_id == bblock_id)
    )
    return [(row.source_id, row.kind) for row in result]


async def replace_register_deps(
    session: AsyncSession, source_register_id: str, edges: set[tuple[str, str]]
) -> None:
    """Replace all outgoing register-level edges for one register (rolled up from bblock_deps
    by the indexer). `edges` is a set of (target_register_id, kind). Flushes first -- see
    replace_bblock_deps for why."""
    await session.flush()
    await session.execute(
        delete(register_deps).where(register_deps.c.source_register_id == source_register_id)
    )
    if edges:
        await session.execute(
            insert(register_deps),
            [
                {"source_register_id": source_register_id, "target_register_id": target_id, "kind": kind}
                for target_id, kind in edges
            ],
        )


async def outgoing_register_deps(session: AsyncSession, register_id: str) -> list[tuple[str, str]]:
    result = await session.execute(
        select(register_deps.c.target_register_id, register_deps.c.kind).where(
            register_deps.c.source_register_id == register_id
        )
    )
    return [(row.target_register_id, row.kind) for row in result]


async def incoming_register_deps(session: AsyncSession, register_id: str) -> list[tuple[str, str]]:
    result = await session.execute(
        select(register_deps.c.source_register_id, register_deps.c.kind).where(
            register_deps.c.target_register_id == register_id
        )
    )
    return [(row.source_register_id, row.kind) for row in result]
