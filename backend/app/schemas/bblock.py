import datetime

from pydantic import BaseModel, ConfigDict


class DepEdge(BaseModel):
    id: str
    kind: str


class BblockSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    register_id: str
    name: str
    abstract: str | None
    status: str | None
    item_class: str | None
    version: str | None
    tags: list[str]
    has_schema: bool
    has_ld_context: bool
    has_shacl_shapes: bool
    matched_chunk_types: list[str] | None = None


class BblockDetail(BblockSummary):
    date_time_addition: str | None
    date_of_last_change: str | None
    schema_urls: dict
    ld_context_url: str | None
    shacl_shapes_urls: list[str]
    sources: list[dict]
    depends_on: list[DepEdge]
    dependents: list[DepEdge]


class BblockListResponse(BaseModel):
    numberMatched: int
    numberReturned: int
    items: list[BblockSummary]


class RegisterDepEdge(BaseModel):
    id: str
    kind: str


class IdentifierConflict(BaseModel):
    id: int
    conflicting_id: str
    existing_register_id: str
    attempted_register_id: str
    detected_at: datetime.datetime
