import datetime

from pydantic import BaseModel

from app.schemas.bblock import IdentifierConflict


class CrawlRun(BaseModel):
    id: int
    register_id: str | None
    started_at: datetime.datetime
    finished_at: datetime.datetime | None
    status: str
    error: str | None


class AdminStatus(BaseModel):
    recent_runs: list[CrawlRun]
    latest_per_register: dict[str, CrawlRun]


class RegisterStatus(BaseModel):
    """Admin-only view of a register's crawl lifecycle -- includes the `status` field
    (pending/crawling/ready/failed), which is deliberately excluded from the public
    RegisterOut schema (app/schemas/register.py)."""

    id: str
    org_id: str
    status: str
    modified: str | None
    last_crawled_at: datetime.datetime | None
    last_crawl_status: str | None
    last_error: str | None


class RegistersStatusResponse(BaseModel):
    registers: list[RegisterStatus]


class ReindexResponse(BaseModel):
    accepted: bool
    register_id: str | None = None


class ConflictsResponse(BaseModel):
    conflicts: list[IdentifierConflict]
