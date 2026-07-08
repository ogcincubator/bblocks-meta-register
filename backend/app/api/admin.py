import asyncio

from fastapi import APIRouter, Depends

from app.api.deps import SessionDep, require_admin_key
from app.crawler.orchestrator import run_crawl_cycle
from app.repositories.conflicts import list_conflicts
from app.repositories.crawl_status import latest_run_per_register, list_recent_runs
from app.repositories.registers import list_registers
from app.schemas.admin import (
    AdminStatus,
    ConflictsResponse,
    CrawlRun,
    ReindexResponse,
    RegisterStatus,
    RegistersStatusResponse,
)

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin_key)])

# Keep references to fire-and-forget reindex tasks so they aren't garbage-collected mid-run.
_background_tasks: set[asyncio.Task] = set()


@router.get("/status", response_model=AdminStatus)
async def admin_status(session: SessionDep) -> AdminStatus:
    recent = [CrawlRun(**run) for run in await list_recent_runs(session)]
    latest = {k: CrawlRun(**v) for k, v in (await latest_run_per_register(session)).items()}
    return AdminStatus(recent_runs=recent, latest_per_register=latest)


@router.get("/registers", response_model=RegistersStatusResponse)
async def admin_registers(session: SessionDep) -> RegistersStatusResponse:
    """Admin-only listing of every register's lifecycle status (pending/crawling/ready/failed),
    for spotting stuck or failed registers without joining crawl_runs -- an alternative to
    /admin/status for deciding which register(s) to target via /admin/reindex."""
    registers = await list_registers(session)
    return RegistersStatusResponse(
        registers=[
            RegisterStatus(
                id=r.id,
                org_id=r.org_id,
                status=r.status,
                modified=r.modified,
                last_crawled_at=r.last_crawled_at,
                last_crawl_status=r.last_crawl_status,
                last_error=r.last_error,
            )
            for r in registers
        ]
    )


@router.get("/conflicts", response_model=ConflictsResponse)
async def admin_conflicts(session: SessionDep) -> ConflictsResponse:
    conflicts = await list_conflicts(session)
    return ConflictsResponse(conflicts=conflicts)


@router.post("/reindex", response_model=ReindexResponse)
async def admin_reindex(register: str | None = None) -> ReindexResponse:
    task = asyncio.create_task(run_crawl_cycle(only_register_id=register))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return ReindexResponse(accepted=True, register_id=register)
