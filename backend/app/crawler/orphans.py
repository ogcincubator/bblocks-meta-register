"""Orphan cleanup: diff the *set* of orgs/register aliases known to the meta-registry against
what's stored locally (not just each known register's bblock list). A register/org no longer
listed gets deleted (cascading through registers -> bblocks), the same way a removed bblock
is deleted within a register that's still present. Distinct from a register that's merely
temporarily unreachable, which is left alone and retried on the next cycle (see
app/crawler/orchestrator.py's failure isolation)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crawler.discovery import Discovery
from app.db.models import Register
from app.repositories.orgs import delete_orgs_not_in
from app.search import keyword_index, vector_store


async def purge_register(session: AsyncSession, register_id: str) -> bool:
    """Delete one register plus its search-index rows. The FTS5/vector tables are virtual and
    have no FK to `registers`, so the cascade that removes bblocks (and bblock_uris/deps) does
    not reach them -- they must be cleared explicitly, and before the row goes, since the
    vector store is keyed by register_url. Returns False if the register wasn't stored."""
    register = await session.get(Register, register_id)
    if register is None:
        return False
    await vector_store.delete_by_register(session, register.register_url)
    await keyword_index.delete_by_register(session, register_id)
    await session.delete(register)
    return True


async def cleanup_orphans(session: AsyncSession, discovery: Discovery) -> dict[str, list[str]]:
    keep_register_ids = {r.register_id for r in discovery.registers}
    keep_org_ids = {o.org_id for o in discovery.orgs}

    stored_ids = set((await session.execute(select(Register.id))).scalars().all())
    deleted_registers = sorted(stored_ids - keep_register_ids)
    for register_id in deleted_registers:
        await purge_register(session, register_id)
    deleted_orgs = await delete_orgs_not_in(session, keep_org_ids)

    return {"deleted_registers": deleted_registers, "deleted_orgs": deleted_orgs}
