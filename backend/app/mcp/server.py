"""MCP server for the meta-registry (docs/02-viewer-application.md's "MCP interface" section) --
lets LLM agents search and traverse the bblock catalog directly instead of parsing REST
responses. Mounted as a sub-app at /mcp (see app/main.py) rather than run as a separate
process, so it reuses the same SQLite engine/session factory as the REST API.

Tools call app.db.base.session_scope() directly rather than going through FastAPI's
Depends()-based SessionDep -- there's no request/response cycle for FastMCP tool functions to
hang a dependency off of. Module-level `session_scope`/`get_embedding_provider` names are
looked up fresh on every call, so tests can monkeypatch them the same way api_client overrides
FastAPI's dependencies (see tests/conftest.py).
"""

from typing import Literal

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from app.config import settings
from app.db.base import session_scope
from app.repositories.bblocks import get_bblock as repo_get_bblock
from app.repositories.bblocks import get_bblocks_by_ids, list_bblocks
from app.repositories.deps import (
    incoming_bblock_deps,
    incoming_bblock_deps_batch,
    incoming_register_deps,
    outgoing_bblock_deps,
    outgoing_bblock_deps_batch,
    outgoing_register_deps,
    traverse_incoming_bblock_deps,
    traverse_incoming_register_deps,
    traverse_outgoing_bblock_deps,
    traverse_outgoing_register_deps,
)
from app.repositories.orgs import get_org as repo_get_org
from app.repositories.orgs import list_orgs
from app.repositories.registers import get_register as repo_get_register
from app.repositories.registers import get_register_url, list_registers
from app.schemas.bblock import BblockDetail, BblockSummary, DepEdge
from app.schemas.org import OrgDetail, OrgSummary
from app.schemas.register import RegisterDepEdge, RegisterDetail, RegisterSummary
from app.search.embeddings import get_embedding_provider
from app.search.service import hybrid_search
from app.services.dependency_graph import MAX_DEPENDENCY_DEPTH

# See config.py's mcp_allowed_hosts/mcp_allowed_origins docstring for why this doesn't rely on
# FastMCP's own built-in localhost default.
_transport_security = (
    TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[h.strip() for h in settings.mcp_allowed_hosts.split(",") if h.strip()],
        allowed_origins=[o.strip() for o in (settings.mcp_allowed_origins or "").split(",") if o.strip()],
    )
    if settings.mcp_allowed_hosts
    else TransportSecuritySettings(enable_dns_rebinding_protection=False)
)

mcp = FastMCP(
    "bblocks-meta-register",
    # Mounted at /mcp in app/main.py -- FastMCP's own default streamable_http_path is also
    # "/mcp", which would otherwise make the effective route /mcp/mcp.
    streamable_http_path="/",
    transport_security=_transport_security,
    instructions=(
        "Search and browse the OGC Building Blocks ecosystem across every register known to "
        "the meta-registry (organization -> register -> bblock). Call search_bblocks first "
        "when looking for building blocks to compose a solution for some use case -- it's "
        "hybrid keyword+semantic search over names, descriptions, schemas, and examples, not a "
        "plain substring match. Use get_bblock/get_register/get_org/list_* to inspect a "
        "specific candidate before recommending it (get_bblocks fetches several bblocks by id "
        "in one call -- prefer it over looping get_bblock over a shortlist), and "
        "bblock_dependencies/register_dependencies to check what it already pulls in or what "
        "depends on it."
    ),
)


@mcp.tool()
async def search_bblocks(
    query: str,
    org: str | None = None,
    register: str | None = None,
    item_class: str | None = None,
    status: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """Hybrid keyword+semantic search for bblocks across every crawled register.

    Use this for open-ended, natural-language use-case questions ("something to model sensor
    observations", "GeoJSON geometry types") as well as keyword lookups -- semantic matches are
    included even when the query text doesn't literally appear. Each result carries
    `matched_chunk_types`, showing whether the hit came from the core metadata, the schema, or
    the examples.

    Args:
        query: Natural-language description or keywords for what's being looked for.
        org: Restrict to one organization's id (e.g. "ogc").
        register: Restrict to one register's alias id (e.g. "ogc/bblocks").
        item_class: Restrict to one item class (e.g. "schema", "datatype", "sosa").
        status: Restrict to one lifecycle status (e.g. "stable", "experimental", "retired").
        limit: Max number of results (1-50).
    """
    limit = max(1, min(limit, 50))
    async with session_scope() as session:
        register_url = await get_register_url(session, register) if register is not None else None
        hits, _total = await hybrid_search(
            session,
            get_embedding_provider(),
            query,
            org=org,
            register_id=register,
            register_url=register_url,
            item_class=item_class,
            status=status,
            limit=limit,
            offset=0,
        )
        bblocks_by_id = await get_bblocks_by_ids(session, [hit.bblock_id for hit in hits])
        results = []
        for hit in hits:
            bblock = bblocks_by_id.get(hit.bblock_id)
            if bblock is None:
                continue  # search index momentarily ahead of a concurrent relational delete
            summary = BblockSummary.model_validate(bblock)
            results.append(
                {
                    **summary.model_dump(exclude={"matched_chunk_types"}),
                    "matched_chunk_types": hit.matched_chunk_types,
                    "score": round(hit.score, 4),
                }
            )
        return results


@mcp.tool()
async def get_bblock(identifier: str) -> dict:
    """Fetch full detail for one bblock by its identifier, including outgoing/incoming
    dependency edges. Raises if the identifier isn't found -- use search_bblocks or
    list_bblocks first if unsure of the exact id."""
    async with session_scope() as session:
        bblock = await repo_get_bblock(session, identifier)
        if bblock is None:
            raise ValueError(f"Bblock '{identifier}' not found")

        depends_on = [DepEdge(id=t, kind=k) for t, k in await outgoing_bblock_deps(session, identifier)]
        dependents = [DepEdge(id=s, kind=k) for s, k in await incoming_bblock_deps(session, identifier)]

        detail = BblockDetail(
            **BblockSummary.model_validate(bblock).model_dump(),
            date_time_addition=bblock.date_time_addition,
            date_of_last_change=bblock.date_of_last_change,
            schema_urls=bblock.schema_urls,
            ld_context_url=bblock.ld_context_url,
            shacl_shapes_urls=bblock.shacl_shapes_urls,
            sources=bblock.sources,
            depends_on=depends_on,
            dependents=dependents,
        )
        return detail.model_dump()


@mcp.tool()
async def get_bblocks(identifiers: list[str]) -> dict:
    """Fetch full detail (including dependency edges) for several bblocks by id in one call --
    use this instead of calling get_bblock in a loop when inspecting a shortlist from
    search_bblocks/list_bblocks_tool. Unknown identifiers are reported in `not_found` rather
    than raising, so one bad id doesn't fail the whole batch.

    Args:
        identifiers: Bblock identifiers to fetch (1-50).
    """
    identifiers = identifiers[:50]
    async with session_scope() as session:
        bblocks_by_id = await get_bblocks_by_ids(session, identifiers)
        found_ids = [i for i in identifiers if i in bblocks_by_id]
        depends_on_batch = await outgoing_bblock_deps_batch(session, found_ids)
        dependents_batch = await incoming_bblock_deps_batch(session, found_ids)

        items = []
        for identifier in found_ids:
            bblock = bblocks_by_id[identifier]
            depends_on = [DepEdge(id=t, kind=k) for t, k in depends_on_batch.get(identifier, [])]
            dependents = [DepEdge(id=s, kind=k) for s, k in dependents_batch.get(identifier, [])]
            detail = BblockDetail(
                **BblockSummary.model_validate(bblock).model_dump(),
                date_time_addition=bblock.date_time_addition,
                date_of_last_change=bblock.date_of_last_change,
                schema_urls=bblock.schema_urls,
                ld_context_url=bblock.ld_context_url,
                shacl_shapes_urls=bblock.shacl_shapes_urls,
                sources=bblock.sources,
                depends_on=depends_on,
                dependents=dependents,
            )
            items.append(detail.model_dump())

        return {
            "items": items,
            "not_found": [i for i in identifiers if i not in bblocks_by_id],
        }


@mcp.tool()
async def list_bblocks_tool(
    org: str | None = None,
    register: str | None = None,
    item_class: str | None = None,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """Browse/filter bblocks without a search query -- plain paginated listing, e.g. "every
    bblock in register X" or "every retired bblock". Use search_bblocks instead when the ask is
    a use case or free-text description rather than an exact filter."""
    limit = max(1, min(limit, 200))
    async with session_scope() as session:
        items, total = await list_bblocks(
            session,
            item_class=item_class,
            status=status,
            register_id=register,
            org_id=org,
            limit=limit,
            offset=offset,
        )
        summaries = [BblockSummary.model_validate(b).model_dump() for b in items]
        return {"numberMatched": total, "numberReturned": len(summaries), "items": summaries}


@mcp.tool()
async def get_register(identifier: str) -> dict:
    """Fetch full detail for one register by its alias id (e.g. "ogc/bblocks"), including its
    bblocks and outgoing/incoming register-level dependency edges. Raises if not found."""
    async with session_scope() as session:
        register = await repo_get_register(session, identifier)
        if register is None:
            raise ValueError(f"Register '{identifier}' not found")

        depends_on = [
            RegisterDepEdge(id=t, kind=k) for t, k in await outgoing_register_deps(session, identifier)
        ]
        dependents = [
            RegisterDepEdge(id=s, kind=k) for s, k in await incoming_register_deps(session, identifier)
        ]

        detail = RegisterDetail(
            **RegisterSummary.model_validate(register).model_dump(),
            modified=register.modified,
            last_crawled_at=register.last_crawled_at,
            last_crawl_status=register.last_crawl_status,
            last_error=register.last_error,
            bblocks=register.bblocks,
            depends_on=depends_on,
            dependents=dependents,
        )
        return detail.model_dump(mode="json")


@mcp.tool()
async def list_registers_tool(org: str | None = None) -> list[dict]:
    """List registers known to the meta-registry, optionally restricted to one organization."""
    async with session_scope() as session:
        registers = await list_registers(session, org_id=org)
        return [RegisterSummary.model_validate(r).model_dump() for r in registers]


@mcp.tool()
async def list_orgs_tool() -> list[dict]:
    """List every organization known to the meta-registry."""
    async with session_scope() as session:
        orgs = await list_orgs(session)
        return [OrgSummary.model_validate(org).model_dump() for org in orgs]


@mcp.tool()
async def get_org(identifier: str) -> dict:
    """Fetch full detail for one organization by its id, including its registers and
    maintainers. Raises if not found."""
    async with session_scope() as session:
        org = await repo_get_org(session, identifier)
        if org is None:
            raise ValueError(f"Org '{identifier}' not found")
        return OrgDetail.model_validate(org).model_dump()


@mcp.tool()
async def bblock_dependencies(
    identifier: str,
    direction: Literal["depends_on", "dependents", "both"] = "both",
    depth: int = 1,
) -> dict:
    """Walk the bblock-to-bblock dependency graph from a starting bblock, in either direction,
    to a given depth. "depends_on" walks outgoing edges (what this bblock needs); "dependents"
    walks incoming edges (what would be affected by a change to this bblock). Each returned
    edge carries a `kind` ("dependsOn", "isProfileOf", etc). A dangling edge (target not
    indexed, e.g. it lives outside the meta-registry) simply doesn't expand further.

    Args:
        identifier: The starting bblock's identifier.
        direction: "depends_on", "dependents", or "both".
        depth: How many hops to walk (1-5).
    """
    depth = max(1, min(depth, MAX_DEPENDENCY_DEPTH))
    async with session_scope() as session:
        if await repo_get_bblock(session, identifier) is None:
            raise ValueError(f"Bblock '{identifier}' not found")

        result: dict[str, list[list[dict]]] = {}
        if direction in ("depends_on", "both"):
            result["depends_on"] = await traverse_outgoing_bblock_deps(session, identifier, depth)
        if direction in ("dependents", "both"):
            result["dependents"] = await traverse_incoming_bblock_deps(session, identifier, depth)
        return result


@mcp.tool()
async def register_dependencies(
    identifier: str,
    direction: Literal["depends_on", "dependents", "both"] = "both",
    depth: int = 1,
) -> dict:
    """Same as bblock_dependencies but at the register level -- register-to-register edges are
    rolled up from the bblock-to-bblock edges their contents form."""
    depth = max(1, min(depth, MAX_DEPENDENCY_DEPTH))
    async with session_scope() as session:
        if await repo_get_register(session, identifier) is None:
            raise ValueError(f"Register '{identifier}' not found")

        result: dict[str, list[list[dict]]] = {}
        if direction in ("depends_on", "both"):
            result["depends_on"] = await traverse_outgoing_register_deps(session, identifier, depth)
        if direction in ("dependents", "both"):
            result["dependents"] = await traverse_incoming_register_deps(session, identifier, depth)
        return result
