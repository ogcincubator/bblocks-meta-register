import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.bblock import BblockSummary, RegisterDepEdge


class RegisterSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    org_id: str
    name: str
    register_url: str
    viewer_url: str | None
    description: str | None


class RegisterDetail(RegisterSummary):
    modified: str | None
    last_crawled_at: datetime.datetime | None
    last_crawl_status: str | None
    last_error: str | None
    bblocks: list[BblockSummary]
    depends_on: list[RegisterDepEdge]
    dependents: list[RegisterDepEdge]
