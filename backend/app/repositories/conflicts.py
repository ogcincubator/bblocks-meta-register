from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tables import identifier_conflicts


async def record_conflict(
    session: AsyncSession, *, conflicting_id: str, existing_register_id: str, attempted_register_id: str
) -> None:
    await session.execute(
        insert(identifier_conflicts),
        {
            "conflicting_id": conflicting_id,
            "existing_register_id": existing_register_id,
            "attempted_register_id": attempted_register_id,
        },
    )


async def list_conflicts(session: AsyncSession) -> list[dict]:
    result = await session.execute(
        select(identifier_conflicts).order_by(identifier_conflicts.c.detected_at.desc())
    )
    return [dict(row._mapping) for row in result]
