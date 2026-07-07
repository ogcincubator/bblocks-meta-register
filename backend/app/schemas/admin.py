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


class ReindexResponse(BaseModel):
    accepted: bool
    register_id: str | None = None


class ConflictsResponse(BaseModel):
    conflicts: list[IdentifierConflict]
