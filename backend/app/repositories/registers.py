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


async def get_registers_by_ids(session: AsyncSession, ids: list[str]) -> dict[str, Register]:
    """Unordered id -> Register lookup for hydrating dependency-graph node ids, mirroring
    get_bblocks_by_ids() -- avoids N+1 session.get() round trips."""
    if not ids:
        return {}
    result = await session.execute(select(Register).where(Register.id.in_(ids)))
    return {register.id: register for register in result.scalars().all()}


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
) -> Register:
    """Note: does *not* touch `modified` -- that's the change-detection field, and it must only
    be advanced once the *entire* crawl pipeline for this register (relational indexing +
    search-content indexing) has succeeded. See set_register_modified()."""
    register = await session.get(Register, register_id)
    if register is None:
        register = Register(id=register_id)
        session.add(register)
    register.org_id = org_id
    register.name = name
    register.register_url = register_url
    register.viewer_url = viewer_url
    register.description = description
    return register


async def set_register_modified(session: AsyncSession, register_id: str, modified: str | None) -> None:
    """Advances the change-detection field once a crawl of this register has fully succeeded
    (relational rows *and* search content committed) -- called at the very end of
    _crawl_one_register(), never from index_register(), so a failure partway through the
    pipeline (e.g. Ollama unreachable during embedding) leaves `modified` at its old value and
    the register is retried on the next crawl cycle instead of being wrongly skipped as
    unchanged."""
    register = await session.get(Register, register_id)
    if register is not None:
        register.modified = modified


async def mark_register_crawling(session: AsyncSession, register_id: str) -> None:
    """Sets the admin-only lifecycle status to "crawling" for the duration of a crawl attempt,
    so a run that never reaches record_crawl_result() (process killed, unhandled crash outside
    _crawl_one_register's try/except) is visible as stuck rather than silently keeping its last
    known-good status."""
    register = await session.get(Register, register_id)
    if register is not None:
        register.status = "crawling"


async def record_crawl_result(
    session: AsyncSession, register_id: str, *, status: str, error: str | None = None
) -> None:
    register = await session.get(Register, register_id)
    if register is None:
        return
    register.last_crawled_at = datetime.datetime.now(datetime.UTC)
    register.last_crawl_status = status
    register.last_error = error
    register.status = "ready" if status == "ok" else "failed"


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
