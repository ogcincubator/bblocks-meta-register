import datetime
from typing import Literal

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
    # Populated only by GET /bblocks/by-uri -- which semantic binding (RDF/vocabulary URI) this
    # bblock matched on, its best-effort schema path, whether the match was exact or a
    # prefix/namespace match, and whether the binding came from the bblock's own ontology file
    # ("ontology"), a declared schema binding ("schema"), or was merely used in an example
    # ("example"). See docs/06-semantic-binding-lookup-plan.md.
    matched_uri: str | None = None
    matched_path: str | None = None
    match_type: Literal["exact", "prefix"] | None = None
    matched_source: Literal["ontology", "schema", "example"] | None = None


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


class GraphNode(BaseModel):
    id: str
    name: str
    known: bool
    register_id: str | None = None
    org_id: str | None = None
    item_class: str | None = None


class GraphEdge(BaseModel):
    source: str
    target: str
    kind: str


class DependencyGraph(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class IdentifierConflict(BaseModel):
    id: int
    conflicting_id: str
    existing_register_id: str
    attempted_register_id: str
    detected_at: datetime.datetime
