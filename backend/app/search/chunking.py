"""Builds the per-register/per-bblock text chunks docs/03-indexing-and-search.md's "Chunking
strategy" describes, ready to hand to an EmbeddingProvider and then a VectorStore.

`bblock_schema` and `bblock_examples` need content that isn't in register.json itself: the
JSON-LD context (`ldContext` URL, field name -> semantic URI mappings) and the per-bblock
`documentation.json-full` doc (which carries fully resolved `examples`, unlike register.json
which only lists bblock metadata). Both are fetched here, one request each per bblock that has
them -- a fetch failure for one bblock's extra content is logged and skipped (that bblock still
gets its `bblock_core` chunk), not allowed to abort the whole register's reindex, matching the
crawler's existing per-register failure isolation (see app/crawler/orchestrator.py).
"""

import logging

import httpx

from app.crawler.discovery import RegisterInfo
from app.crawler.http import get_json
from app.search.vector_store import Chunk

logger = logging.getLogger(__name__)

# doc 03's "Chunk size limits for very large examples" open question -- picked a conservative
# default cap rather than leaving examples unbounded; revisit once real-world example sizes
# across registers are surveyed.
EXAMPLE_CHUNK_CHAR_LIMIT = 2000


def _register_summary_text(register_json: dict) -> str:
    parts = [register_json.get("name"), register_json.get("abstract"), register_json.get("description")]
    return "\n".join(p for p in parts if p)


def _bblock_core_text(raw_bblock: dict) -> str:
    parts = [raw_bblock.get("name"), raw_bblock.get("abstract")]

    item_class = raw_bblock.get("itemClass")
    if item_class:
        parts.append(f"Type: {item_class}")

    status = raw_bblock.get("status")
    if status:
        parts.append(f"Status: {status}")

    tags = raw_bblock.get("tags") or []
    if tags:
        parts.append("Tags: " + ", ".join(tags))

    sources = raw_bblock.get("sources") or []
    titles = [s.get("title") for s in sources if isinstance(s, dict) and s.get("title")]
    if titles:
        parts.append("Sources: " + ", ".join(titles))

    transforms = raw_bblock.get("transforms") or []
    descriptions = [t.get("description") for t in transforms if isinstance(t, dict) and t.get("description")]
    if descriptions:
        parts.append("Transforms: " + "; ".join(descriptions))

    return "\n".join(p for p in parts if p)


def _ld_context_fields(ld_context_json: dict) -> list[tuple[str, str]]:
    """A JSON-LD `@context` maps short field names to either a URI string directly, or an
    object carrying `@id`; `@`-prefixed keys (`@version`, `@vocab`, ...) are context directives,
    not field mappings, and namespace-prefix-only entries (a bare string with no field meaning
    of its own) are indistinguishable from a real field mapping at this level, so both are kept
    -- a false positive here just adds a low-signal chunk line, not a wrong search result."""
    context = ld_context_json.get("@context")
    contexts = context if isinstance(context, list) else [context]

    fields: list[tuple[str, str]] = []
    for ctx in contexts:
        if not isinstance(ctx, dict):
            continue
        for key, value in ctx.items():
            if key.startswith("@"):
                continue
            if isinstance(value, str):
                uri = value
            elif isinstance(value, dict):
                uri = value.get("@id")
            else:
                continue
            if uri:
                fields.append((key, uri))
    return fields


def _bblock_schema_text(ld_context_json: dict) -> str:
    return "\n".join(f"{key}: {uri}" for key, uri in _ld_context_fields(ld_context_json))


def _resolved_properties_text(resolved_properties_json: dict) -> str:
    """Fallback source for the `bblock_schema` chunk when a bblock has no `ldContext` (property
    names only, no semantic URIs) -- `resolvedSchemaProperties` is the schema with `$ref`/`allOf`
    already flattened into a dotted-path property list, same flattening the JSON-LD context gets
    for free but the raw schema wouldn't have without resolving refs itself."""
    names = []
    for prop in resolved_properties_json.get("properties") or []:
        path = prop.get("path")
        if isinstance(path, list) and path:
            names.append(".".join(str(segment) for segment in path))
    return "\n".join(dict.fromkeys(names))


def _bblock_examples_text(json_full_doc: dict) -> str:
    parts = []
    for example in json_full_doc.get("examples") or []:
        if not isinstance(example, dict):
            continue
        if title := example.get("title"):
            parts.append(title)
        snippet = next(
            (s.get("code") for s in example.get("snippets") or [] if s.get("language") == "json" and s.get("code")),
            None,
        )
        if snippet:
            parts.append(snippet)
    return "\n".join(parts)[:EXAMPLE_CHUNK_CHAR_LIMIT]


async def build_register_chunks(
    client: httpx.AsyncClient, register_info: RegisterInfo, register_json: dict
) -> list[Chunk]:
    chunks: list[Chunk] = []

    summary_text = _register_summary_text(register_json)
    if summary_text:
        chunks.append(
            Chunk(
                key=f"register_summary:{register_info.register_url}",
                text=summary_text,
                chunk_type="register_summary",
                org=register_info.org_id,
                register_url=register_info.register_url,
            )
        )

    for raw_bblock in register_json.get("bblocks", []):
        bblock_id = raw_bblock.get("itemIdentifier")
        if not bblock_id:
            continue
        item_class = raw_bblock.get("itemClass")
        status = raw_bblock.get("status")

        core_text = _bblock_core_text(raw_bblock)
        if core_text:
            chunks.append(
                Chunk(
                    key=f"bblock_core:{bblock_id}",
                    text=core_text,
                    chunk_type="bblock_core",
                    org=register_info.org_id,
                    register_url=register_info.register_url,
                    bblock_id=bblock_id,
                    item_class=item_class,
                    status=status,
                )
            )

        schema_text = ""
        ld_context_url = raw_bblock.get("ldContext")
        if ld_context_url:
            try:
                ld_context_json = await get_json(client, ld_context_url)
            except httpx.HTTPError as exc:
                logger.warning("Failed to fetch ldContext for %s: %s", bblock_id, exc)
            else:
                if isinstance(ld_context_json, dict):
                    schema_text = _bblock_schema_text(ld_context_json)

        if not schema_text:
            resolved_url = raw_bblock.get("resolvedSchemaProperties")
            if resolved_url:
                try:
                    resolved_json = await get_json(client, resolved_url)
                except httpx.HTTPError as exc:
                    logger.warning("Failed to fetch resolvedSchemaProperties for %s: %s", bblock_id, exc)
                else:
                    if isinstance(resolved_json, dict):
                        schema_text = _resolved_properties_text(resolved_json)

        if schema_text:
            chunks.append(
                Chunk(
                    key=f"bblock_schema:{bblock_id}",
                    text=schema_text,
                    chunk_type="bblock_schema",
                    org=register_info.org_id,
                    register_url=register_info.register_url,
                    bblock_id=bblock_id,
                    item_class=item_class,
                    status=status,
                )
            )

        json_full_url = (raw_bblock.get("documentation") or {}).get("json-full", {}).get("url")
        if json_full_url:
            try:
                json_full_doc = await get_json(client, json_full_url)
            except httpx.HTTPError as exc:
                logger.warning("Failed to fetch json-full doc for %s: %s", bblock_id, exc)
            else:
                if isinstance(json_full_doc, dict):
                    examples_text = _bblock_examples_text(json_full_doc)
                    if examples_text:
                        chunks.append(
                            Chunk(
                                key=f"bblock_examples:{bblock_id}",
                                text=examples_text,
                                chunk_type="bblock_examples",
                                org=register_info.org_id,
                                register_url=register_info.register_url,
                                bblock_id=bblock_id,
                                item_class=item_class,
                                status=status,
                            )
                        )

    return chunks
