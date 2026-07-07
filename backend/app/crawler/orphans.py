"""Orphan cleanup: diff the *set* of orgs/register aliases known to the meta-registry against
what's stored locally (not just each known register's bblock list). A register/org no longer
listed gets deleted (cascading through registers -> bblocks), the same way a removed bblock
is deleted within a register that's still present. Distinct from a register that's merely
temporarily unreachable, which is left alone and retried on the next cycle (see
app/crawler/orchestrator.py's failure isolation)."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.crawler.discovery import Discovery
from app.repositories.orgs import delete_orgs_not_in
from app.repositories.registers import delete_registers_not_in


async def cleanup_orphans(session: AsyncSession, discovery: Discovery) -> dict[str, list[str]]:
    keep_register_ids = {r.register_id for r in discovery.registers}
    keep_org_ids = {o.org_id for o in discovery.orgs}

    deleted_registers = await delete_registers_not_in(session, keep_register_ids)
    deleted_orgs = await delete_orgs_not_in(session, keep_org_ids)

    return {"deleted_registers": deleted_registers, "deleted_orgs": deleted_orgs}
