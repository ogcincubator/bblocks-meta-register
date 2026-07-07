import datetime

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tables import crawl_runs


async def start_run(session: AsyncSession, register_id: str | None = None) -> int:
    result = await session.execute(
        insert(crawl_runs).values(
            register_id=register_id,
            started_at=datetime.datetime.now(datetime.UTC),
            status="running",
        )
    )
    await session.flush()
    return result.inserted_primary_key[0]


async def finish_run(session: AsyncSession, run_id: int, *, status: str, error: str | None = None) -> None:
    await session.execute(
        update(crawl_runs)
        .where(crawl_runs.c.id == run_id)
        .values(finished_at=datetime.datetime.now(datetime.UTC), status=status, error=error)
    )


async def list_recent_runs(session: AsyncSession, limit: int = 50) -> list[dict]:
    result = await session.execute(
        select(crawl_runs).order_by(crawl_runs.c.started_at.desc()).limit(limit)
    )
    return [dict(row._mapping) for row in result]


async def latest_run_per_register(session: AsyncSession) -> dict[str, dict]:
    """Most recent run per register_id (excludes whole-cycle rows where register_id is null)."""
    runs = await list_recent_runs(session, limit=1000)
    latest: dict[str, dict] = {}
    for run in runs:
        register_id = run["register_id"]
        if register_id is None or register_id in latest:
            continue
        latest[register_id] = run
    return latest
