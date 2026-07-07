"""Shared BFS dependency-graph traversal, used by both the MCP tools (app/mcp/server.py) and
the REST graph endpoints (app/api/bblocks.py, app/api/registers.py). A dangling edge target
(not indexed in the meta-registry) is still included as an "unknown" node -- name falls back to
the raw id, no register/org/item_class, not further expanded -- rather than silently dropped,
so the graph shows the full shape of what a bblock/register depends on.
"""

from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.bblocks import get_bblocks_by_ids
from app.repositories.deps import (
    traverse_incoming_bblock_deps,
    traverse_incoming_register_deps,
    traverse_outgoing_bblock_deps,
    traverse_outgoing_register_deps,
)
from app.repositories.registers import get_registers_by_ids

MAX_DEPENDENCY_DEPTH = 5

Direction = Literal["depends_on", "dependents", "both"]


def _flatten(levels: list[list[dict]]) -> list[dict]:
    return [edge for level in levels for edge in level]


def _flatten_reversed(levels: list[list[dict]]) -> list[dict]:
    """Like _flatten, but for edges discovered via an incoming/"dependents" traversal:
    traverse_incoming_*_deps' "from"/"to" there mean "node walked from" / "node discovered",
    which for an incoming edge is (dependee, depender) -- the reverse of the actual
    dependsOn/isProfileOf relationship. Swap them so graph edges always point depender ->
    dependee, matching the outgoing-traversal edges and how a dependency arrow should read."""
    return [{"from": edge["to"], "to": edge["from"], "kind": edge["kind"]} for level in levels for edge in level]


@dataclass
class GraphNodeData:
    id: str
    name: str
    known: bool
    register_id: str | None = None
    org_id: str | None = None
    item_class: str | None = None


@dataclass
class GraphEdgeData:
    source: str
    target: str
    kind: str


@dataclass
class GraphData:
    nodes: list[GraphNodeData]
    edges: list[GraphEdgeData]


async def build_bblock_graph(
    session: AsyncSession, start_id: str, direction: Direction, depth: int
) -> GraphData:
    depth = max(1, min(depth, MAX_DEPENDENCY_DEPTH))

    raw_edges: list[dict] = []
    if direction in ("depends_on", "both"):
        raw_edges += _flatten(await traverse_outgoing_bblock_deps(session, start_id, depth))
    if direction in ("dependents", "both"):
        raw_edges += _flatten_reversed(await traverse_incoming_bblock_deps(session, start_id, depth))

    node_ids = {start_id, *(e["from"] for e in raw_edges), *(e["to"] for e in raw_edges)}
    bblocks_by_id = await get_bblocks_by_ids(session, list(node_ids))

    nodes = []
    for node_id in node_ids:
        bblock = bblocks_by_id.get(node_id)
        if bblock is not None:
            org_id = bblock.register_id.split("/", 1)[0] if "/" in bblock.register_id else None
            nodes.append(
                GraphNodeData(
                    id=node_id,
                    name=bblock.name,
                    known=True,
                    register_id=bblock.register_id,
                    org_id=org_id,
                    item_class=bblock.item_class,
                )
            )
        else:
            nodes.append(GraphNodeData(id=node_id, name=node_id, known=False))

    edges = [GraphEdgeData(source=e["from"], target=e["to"], kind=e["kind"]) for e in raw_edges]
    return GraphData(nodes=nodes, edges=edges)


async def build_register_graph(
    session: AsyncSession, start_id: str, direction: Direction, depth: int
) -> GraphData:
    depth = max(1, min(depth, MAX_DEPENDENCY_DEPTH))

    raw_edges: list[dict] = []
    if direction in ("depends_on", "both"):
        raw_edges += _flatten(await traverse_outgoing_register_deps(session, start_id, depth))
    if direction in ("dependents", "both"):
        raw_edges += _flatten_reversed(await traverse_incoming_register_deps(session, start_id, depth))

    node_ids = {start_id, *(e["from"] for e in raw_edges), *(e["to"] for e in raw_edges)}
    registers_by_id = await get_registers_by_ids(session, list(node_ids))

    nodes = []
    for node_id in node_ids:
        register = registers_by_id.get(node_id)
        if register is not None:
            nodes.append(
                GraphNodeData(
                    id=node_id,
                    name=register.name,
                    known=True,
                    register_id=register.id,
                    org_id=register.org_id,
                )
            )
        else:
            nodes.append(GraphNodeData(id=node_id, name=node_id, known=False))

    edges = [GraphEdgeData(source=e["from"], target=e["to"], kind=e["kind"]) for e in raw_edges]
    return GraphData(nodes=nodes, edges=edges)
