import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Register


async def list_registers(session: AsyncSession, *, org_id: str | None = None) -> list[Register]:
    stmt = select(Register).order_by(Register.id)
    if org_id is not None:
        stmt = stmt.where(Register.org_id == org_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_register(session: AsyncSession, register_id: str) -> Register | None:
    result = await session.execute(
        select(Register).where(Register.id == register_id).options(selectinload(Register.bblocks))
    )
    return result.scalar_one_or_none()


async def get_register_by_url(session: AsyncSession, register_url: str) -> Register | None:
    result = await session.execute(select(Register).where(Register.register_url == register_url))
    return result.scalar_one_or_none()


async def get_register_url(session: AsyncSession, register_id: str) -> str | None:
    """Resolves a register alias (e.g. "ogc/main") to its register.json URL -- needed to filter
    hybrid search's vector pass, since vector_chunks is keyed by register_url, not register_id
    (see app/search/vector_store.py)."""
    result = await session.execute(select(Register.register_url).where(Register.id == register_id))
    return result.scalar_one_or_none()


async def get_register_modified(session: AsyncSession, register_id: str) -> str | None:
    """Lightweight lookup of just the change-detection field, avoiding the bblocks join
    that get_register() incurs via selectinload -- called once per register on every crawl."""
    result = await session.execute(select(Register.modified).where(Register.id == register_id))
    return result.scalar_one_or_none()


async def upsert_register(
    session: AsyncSession,
    *,
    register_id: str,
    org_id: str,
    name: str,
    register_url: str,
    viewer_url: str | None,
    description: str | None,
    modified: str | None,
) -> Register:
    register = await session.get(Register, register_id)
    if register is None:
        register = Register(id=register_id)
        session.add(register)
    register.org_id = org_id
    register.name = name
    register.register_url = register_url
    register.viewer_url = viewer_url
    register.description = description
    register.modified = modified
    return register


async def record_crawl_result(
    session: AsyncSession, register_id: str, *, status: str, error: str | None = None
) -> None:
    register = await session.get(Register, register_id)
    if register is None:
        return
    register.last_crawled_at = datetime.datetime.now(datetime.UTC)
    register.last_crawl_status = status
    register.last_error = error


async def delete_registers_not_in(session: AsyncSession, keep_ids: set[str]) -> list[str]:
    """Delete registers whose alias id is not in `keep_ids` (cascades to bblocks). Returns deleted ids."""
    result = await session.execute(select(Register.id))
    existing_ids = set(result.scalars().all())
    to_delete = existing_ids - keep_ids
    for register_id in to_delete:
        register = await session.get(Register, register_id)
        if register is not None:
            await session.delete(register)
    return list(to_delete)
