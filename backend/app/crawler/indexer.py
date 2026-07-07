"""Full-replace indexing of one register's relational metadata (no embedding/chunking --
that's docs/03-indexing-and-search.md, deferred).

Per docs/02-viewer-application.md, when a register's content changed, its data is fully
replaced rather than diffed bblock-by-bblock: delete existing rows, then re-insert
everything currently in register.json.
"""

import logging

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.crawler.discovery import RegisterInfo
from app.repositories.bblocks import delete_bblocks_for_register, get_owning_register_id, upsert_bblock
from app.repositories.conflicts import record_conflict
from app.repositories.deps import outgoing_bblock_deps, replace_bblock_deps, replace_register_deps
from app.repositories.registers import upsert_register
from app.search import keyword_index, vector_store
from app.search.chunking import build_register_chunks
from app.search.embeddings import EmbeddingProvider

logger = logging.getLogger(__name__)


def _normalize_target_id(target: str) -> str:
    """dependsOn/isProfileOf targets are seen in the wild both as bare itemIdentifiers and as
    `bblocks://itemIdentifier` URIs (the scheme docs/01-overall-architecture.md describes).
    Strip the scheme so the edge's target_id matches the same id format used as bblocks.id --
    otherwise a real dependency would never resolve to its owning register (see
    outgoing_register_deps roll-up) even once the target is indexed."""
    prefix = "bblocks://"
    return target[len(prefix):] if target.startswith(prefix) else target


def _extract_edges(raw_bblock: dict) -> list[tuple[str, str]]:
    """(target_id, kind) pairs from a bblock's dependsOn/isProfileOf fields (a list for
    dependsOn, possibly a single string or a list for isProfileOf) -- normalize both shapes."""
    edges = []
    for field, kind in (("dependsOn", "dependsOn"), ("isProfileOf", "isProfileOf")):
        value = raw_bblock.get(field)
        if not value:
            continue
        targets = value if isinstance(value, list) else [value]
        edges.extend(
            (_normalize_target_id(target), kind) for target in targets if isinstance(target, str) and target
        )
    return edges


def _extract_presence(raw_bblock: dict) -> tuple[dict, str | None, list[str]]:
    """schema/shaclShapes are objects keyed by media type in real register.json output, not
    a single URL -- presence is "non-empty", not "field is set"."""
    schema_urls = raw_bblock.get("schema")
    schema_urls = schema_urls if isinstance(schema_urls, dict) else {}

    ld_context_url = raw_bblock.get("ldContext") or None

    shacl_shapes = raw_bblock.get("shaclShapes")
    if isinstance(shacl_shapes, dict):
        shacl_shapes_urls = list(shacl_shapes.values())
    elif isinstance(shacl_shapes, list):
        shacl_shapes_urls = shacl_shapes
    else:
        shacl_shapes_urls = []

    return schema_urls, ld_context_url, shacl_shapes_urls


async def index_register(session: AsyncSession, register_info: RegisterInfo, register_json: dict) -> list[str]:
    """Full-replace relational indexing. Returns the itemIdentifiers actually accepted (i.e.
    excluding any rejected for an identifier conflict) -- index_search_content() below uses
    this to keep the FTS5/vector indexes limited to the same set of bblocks as the relational
    tables, rather than re-deriving accepted-ness itself."""
    register_id = register_info.register_id

    await upsert_register(
        session,
        register_id=register_id,
        org_id=register_info.org_id,
        name=register_json.get("name") or register_info.name,
        register_url=register_info.register_url,
        viewer_url=register_json.get("viewerURL"),
        description=register_json.get("abstract") or register_json.get("description"),
        modified=register_json.get("modified"),
    )

    # Full replace: this register's own bblocks are cleared first, so any owner found below
    # for a given itemIdentifier belongs to a *different* register -- a genuine conflict.
    await delete_bblocks_for_register(session, register_id)

    indexed_ids: list[str] = []
    for raw_bblock in register_json.get("bblocks", []):
        bblock_id = raw_bblock.get("itemIdentifier")
        if not bblock_id:
            logger.warning("Skipping bblock with no itemIdentifier in register %s", register_id)
            continue

        existing_owner = await get_owning_register_id(session, bblock_id)
        if existing_owner is not None and existing_owner != register_id:
            await record_conflict(
                session,
                conflicting_id=bblock_id,
                existing_register_id=existing_owner,
                attempted_register_id=register_id,
            )
            logger.warning(
                "Identifier conflict: %s already owned by %s, rejecting claim from %s",
                bblock_id,
                existing_owner,
                register_id,
            )
            continue

        schema_urls, ld_context_url, shacl_shapes_urls = _extract_presence(raw_bblock)
        await upsert_bblock(
            session,
            bblock_id=bblock_id,
            register_id=register_id,
            name=raw_bblock.get("name", bblock_id),
            abstract=raw_bblock.get("abstract"),
            status=raw_bblock.get("status"),
            item_class=raw_bblock.get("itemClass"),
            version=raw_bblock.get("version"),
            tags=raw_bblock.get("tags") or [],
            date_time_addition=raw_bblock.get("dateTimeAddition"),
            date_of_last_change=raw_bblock.get("dateOfLastChange"),
            has_schema=bool(schema_urls),
            has_ld_context=bool(ld_context_url),
            has_shacl_shapes=bool(shacl_shapes_urls),
            schema_urls=schema_urls,
            ld_context_url=ld_context_url,
            shacl_shapes_urls=shacl_shapes_urls,
            sources=raw_bblock.get("sources") or [],
        )
        await replace_bblock_deps(session, bblock_id, _extract_edges(raw_bblock))
        indexed_ids.append(bblock_id)

    # Roll up bblock-level edges to register-level edges (register.json has no separate
    # `imports`-equivalent field, so this is the only source of register_deps).
    register_edges: set[tuple[str, str]] = set()
    for bblock_id in indexed_ids:
        for target_id, kind in await outgoing_bblock_deps(session, bblock_id):
            target_register_id = await get_owning_register_id(session, target_id)
            if target_register_id and target_register_id != register_id:
                register_edges.add((target_register_id, kind))
    await replace_register_deps(session, register_id, register_edges)

    return indexed_ids


async def index_search_content(
    session: AsyncSession,
    client: httpx.AsyncClient,
    embedding_provider: EmbeddingProvider,
    register_info: RegisterInfo,
    register_json: dict,
    indexed_ids: list[str],
) -> None:
    """Full-replace of this register's FTS5 keyword rows and vector chunks (docs/03's "when a
    register's content hash changes, that register's data is fully replaced" -- applies to the
    search indexes the same way it applies to the relational rows in index_register() above).
    Only bblocks in `indexed_ids` (i.e. not rejected for an identifier conflict) are indexed.
    """
    await vector_store.delete_by_register(session, register_info.register_url)
    await keyword_index.delete_by_register(session, register_info.register_id)

    indexed_ids_set = set(indexed_ids)
    accepted_bblocks = [b for b in register_json.get("bblocks", []) if b.get("itemIdentifier") in indexed_ids_set]
    filtered_register_json = {**register_json, "bblocks": accepted_bblocks}

    chunks = await build_register_chunks(client, register_info, filtered_register_json)
    if chunks:
        embeddings = await embedding_provider.embed_documents([chunk.text for chunk in chunks])
        await vector_store.upsert_chunks(session, chunks, embeddings)

    for raw_bblock in accepted_bblocks:
        await keyword_index.upsert(
            session,
            bblock_id=raw_bblock["itemIdentifier"],
            register_id=register_info.register_id,
            org=register_info.org_id,
            item_class=raw_bblock.get("itemClass"),
            status=raw_bblock.get("status"),
            name=raw_bblock.get("name", raw_bblock["itemIdentifier"]),
            abstract=raw_bblock.get("abstract"),
            tags=raw_bblock.get("tags") or [],
        )
