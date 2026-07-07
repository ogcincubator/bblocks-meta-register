from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Org


async def list_orgs(session: AsyncSession) -> list[Org]:
    result = await session.execute(select(Org).order_by(Org.id))
    return list(result.scalars().all())


async def get_org(session: AsyncSession, org_id: str) -> Org | None:
    result = await session.execute(
        select(Org).where(Org.id == org_id).options(selectinload(Org.registers))
    )
    return result.scalar_one_or_none()


async def upsert_org(
    session: AsyncSession,
    *,
    org_id: str,
    name: str,
    description: str | None,
    url: str | None,
    maintainers: list[dict],
) -> Org:
    org = await session.get(Org, org_id)
    if org is None:
        org = Org(id=org_id)
        session.add(org)
    org.name = name
    org.description = description
    org.url = url
    org.maintainers = maintainers
    return org


async def delete_orgs_not_in(session: AsyncSession, keep_ids: set[str]) -> list[str]:
    """Delete orgs whose id is not in `keep_ids` (cascades to registers/bblocks). Returns deleted ids."""
    result = await session.execute(select(Org.id))
    existing_ids = set(result.scalars().all())
    to_delete = existing_ids - keep_ids
    for org_id in to_delete:
        org = await session.get(Org, org_id)
        if org is not None:
            await session.delete(org)
    return list(to_delete)
