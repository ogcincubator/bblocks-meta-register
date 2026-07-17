"""Builds the per-register/per-bblock text chunks docs/03-indexing-and-search.md's "Chunking
strategy" describes, ready to hand to an EmbeddingProvider and then a VectorStore.

`bblock_schema`, `bblock_description` and `bblock_usage` need content that isn't in
register.json itself: the JSON-LD context (`ldContext` URL, field name -> semantic URI
mappings) and the per-bblock `documentation.json-full` doc (which carries fully resolved
`examples` and the bblock's full `description`, unlike register.json which only lists bblock
metadata -- no per-bblock `description` field). Both are fetched here, one request each per
bblock that has them. `json-full` is this bblock's main metadata document, so a failure to
fetch or process it is *not* best-effort -- the whole bblock is logged and skipped (no chunks
at all for it this cycle) rather than silently emitting a description-less chunk. `ldContext`
and `resolvedSchemaProperties`, by contrast, only feed the `bblock_schema` chunk and are
genuinely best-effort: a failure there is logged and that one chunk is dropped, the rest of the
bblock's chunks are still built. Either way, one bblock's failure is never allowed to abort the
whole register's reindex, matching the crawler's existing per-register failure isolation (see
app/crawler/orchestrator.py).

`description` is kept as its own `bblock_description` chunk rather than folded into
`bblock_core`: chunk merging in app/search/service.py takes the *best*-scoring chunk per
bblock, not an average, so splitting only helps recall -- a short, precise `bblock_core` chunk
won't have its embedding diluted by a long markdown description, and a query that matches the
description closely isn't held back by unrelated metadata sharing the same chunk.
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


def _bblock_description_text(json_full_doc: dict) -> str:
    description = json_full_doc.get("description")
    return description if isinstance(description, str) else ""


def _bblock_core_text(raw_bblock: dict) -> str:
    # Kept to just the short, precise identity fields -- `description` (bblock_description),
    # and `sources`/`transforms` (bblock_usage, alongside examples) are embedded as their own
    # chunks instead (see build_register_chunks) so their content doesn't dilute this chunk's
    # embedding, and vice versa. `itemClass`/`status` are deliberately left out entirely: both
    # are already exact-match query filters on hybrid_search, so embedding them as free text
    # would only add noise, not recall.
    parts = [raw_bblock.get("name"), raw_bblock.get("abstract")]

    tags = raw_bblock.get("tags") or []
    if tags:
        parts.append("Tags: " + ", ".join(tags))

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


def _bblock_usage_text(raw_bblock: dict, json_full_doc: dict) -> str:
    """`sources` (specs/papers this block is based on) and `transforms` (conversions it
    supports, e.g. "convert to CSV") describe how this block relates to and can be used with
    other formats/standards -- the same "practical usage" territory as its examples, so all
    three share one chunk rather than each getting a thin chunk of its own. Sources/transforms
    come from raw_bblock (register.json) and are placed first, ahead of the truncatable
    examples text, so they're never lost to EXAMPLE_CHUNK_CHAR_LIMIT."""
    parts = []

    sources = raw_bblock.get("sources") or []
    titles = [s.get("title") for s in sources if isinstance(s, dict) and s.get("title")]
    if titles:
        parts.append("Sources: " + ", ".join(titles))

    transforms = raw_bblock.get("transforms") or []
    transform_descriptions = [t.get("description") for t in transforms if isinstance(t, dict) and t.get("description")]
    if transform_descriptions:
        parts.append("Transforms: " + "; ".join(transform_descriptions))

    for example in json_full_doc.get("examples") or []:
        if not isinstance(example, dict):
            continue
        if title := example.get("title"):
            parts.append(title)
        # `content` is the example's own Markdown description (examples.yaml's "content" field)
        # -- often carries use-case prose that isn't repeated anywhere else, so it's as valuable
        # to search as the title.
        if content := example.get("content"):
            parts.append(content)
        snippet = next(
            (s.get("code") for s in example.get("snippets") or [] if s.get("language") == "json" and s.get("code")),
            None,
        )
        if snippet:
            parts.append(snippet)

    return "\n".join(parts)[:EXAMPLE_CHUNK_CHAR_LIMIT]


async def build_register_chunks(
    client: httpx.AsyncClient, register_info: RegisterInfo, register_json: dict
) -> tuple[list[Chunk], dict[str, str], list[str]]:
    """Returns the chunks to embed, a bblock_id -> description map (sourced from the same
    json-full doc fetched below for the bblock_description chunk, not register.json -- which has
    no per-bblock description field) for the caller to also feed into the FTS5 keyword index, and
    the ids of bblocks whose main (json-full) metadata failed to fetch -- the caller uses this to
    surface the register as having partial results rather than a silent full success."""
    chunks: list[Chunk] = []
    descriptions: dict[str, str] = {}
    failed_bblock_ids: list[str] = []

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

        logger.info("Fetching search content for bblock %s (register %s)", bblock_id, register_info.register_id)

        # Fetched first (rather than alongside the bblock_usage chunk further down) so its
        # `description` field -- absent from register.json -- is available for the
        # bblock_description chunk below.
        json_full_doc: dict = {}
        json_full_url = (raw_bblock.get("documentation") or {}).get("json-full", {}).get("url")
        if json_full_url:
            try:
                fetched = await get_json(client, json_full_url)
            except Exception as exc:  # noqa: BLE001 - main metadata: skip this bblock, not best-effort
                logger.error(
                    "Skipping bblock %s (register %s): failed to fetch main metadata from %s: %s",
                    bblock_id,
                    register_info.register_id,
                    json_full_url,
                    exc,
                )
                failed_bblock_ids.append(bblock_id)
                continue
            if isinstance(fetched, dict):
                json_full_doc = fetched

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

        description = _bblock_description_text(json_full_doc)
        if description:
            descriptions[bblock_id] = description
            chunks.append(
                Chunk(
                    key=f"bblock_description:{bblock_id}",
                    text=description,
                    chunk_type="bblock_description",
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
            except Exception as exc:  # noqa: BLE001 - best-effort: skip this chunk, keep the bblock
                logger.warning("Failed to fetch ldContext for %s from %s: %s", bblock_id, ld_context_url, exc)
            else:
                if isinstance(ld_context_json, dict):
                    schema_text = _bblock_schema_text(ld_context_json)

        if not schema_text:
            resolved_url = raw_bblock.get("resolvedSchemaProperties")
            if resolved_url:
                try:
                    resolved_json = await get_json(client, resolved_url)
                except Exception as exc:  # noqa: BLE001 - best-effort: skip this chunk, keep the bblock
                    logger.warning(
                        "Failed to fetch resolvedSchemaProperties for %s from %s: %s", bblock_id, resolved_url, exc
                    )
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

        usage_text = _bblock_usage_text(raw_bblock, json_full_doc)
        if usage_text:
            chunks.append(
                Chunk(
                    key=f"bblock_usage:{bblock_id}",
                    text=usage_text,
                    chunk_type="bblock_usage",
                    org=register_info.org_id,
                    register_url=register_info.register_url,
                    bblock_id=bblock_id,
                    item_class=item_class,
                    status=status,
                )
            )

    return chunks, descriptions, failed_bblock_ids
