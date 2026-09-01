"""Builds the per-register/per-bblock text chunks docs/03-indexing-and-search.md's "Chunking
strategy" describes, ready to hand to an EmbeddingProvider and then a VectorStore. Also builds
the (path, uri, source) semantic-binding triples that feed the `bblock_uris` reverse index (see
docs/06-semantic-binding-lookup-plan.md) -- a query-time lookup, not a search chunk. Three
sources feed it, in descending confidence order: the bblock's own `ontology` file, if any
(source="ontology" -- a term this bblock *defines*, not merely binds to; see "Ontology-derived
bindings" in doc 06), `resolvedSchemaProperties` (source="schema" -- a binding the bblock's
author declared on a schema property), and each example's Turtle snippet, if any
(source="example" -- a term the bblock's sample data merely *uses*; see "Example-derived
bindings" in doc 06). `source` lets a caller rank a bblock's own vocabulary definitions ahead of
a declared external binding, and either ahead of an incidental one, at the same match_type.

`bblock_schema`, `bblock_description` and `bblock_usage` need content that isn't in
register.json itself: the JSON-LD context (`ldContext` URL, field name -> semantic URI
mappings) and the per-bblock `documentation.json-full` doc (which carries fully resolved
`examples` and the bblock's full `description`, unlike register.json which only lists bblock
metadata -- no per-bblock `description` field). Both are fetched here, one request each per
bblock that has them. `json-full` is this bblock's main metadata document, so a failure to
fetch or process it is *not* best-effort -- the whole bblock is logged and skipped (no chunks
at all for it this cycle) rather than silently emitting a description-less chunk. `ldContext`
and `resolvedSchemaProperties`, by contrast, are genuinely best-effort: a failure there is
logged and that one chunk (or, for `resolvedSchemaProperties`, the semantic-binding pairs too)
is dropped, the rest of the bblock's chunks are still built. `resolvedSchemaProperties` is now
fetched whenever `register.json` has it, not only when `ldContext` is absent -- it's the source
of truth for `bblock_uris` regardless of whether `ldContext` already produced a usable
`bblock_schema` chunk (see "Why resolvedProperties.json, not the raw JSON-LD @context" in doc
06 for why the raw `ldContext` values aren't reliable enough for exact URI lookup: a `@context`
term's value can be an unexpanded CURIE). Either way, one bblock's failure is never allowed to
abort the whole register's reindex, matching the crawler's existing per-register failure
isolation (see app/crawler/orchestrator.py).

`description` is kept as its own `bblock_description` chunk rather than folded into
`bblock_core`: chunk merging in app/search/service.py takes the *best*-scoring chunk per
bblock, not an average, so splitting only helps recall -- a short, precise `bblock_core` chunk
won't have its embedding diluted by a long markdown description, and a query that matches the
description closely isn't held back by unrelated metadata sharing the same chunk.
"""

import logging
from urllib.parse import urlsplit

import httpx
from rdflib import Graph, URIRef
from rdflib.namespace import RDF

from app.crawler.discovery import RegisterInfo
from app.crawler.http import get_json, get_text
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


def _resolved_property_bindings(resolved_properties_json: dict) -> list[tuple[str, str]]:
    """(path, uri) pairs for every resolved property with a semantic binding, sourced from
    `effectiveId` (see docs/06-semantic-binding-lookup-plan.md's format reference -- already a
    fully-expanded absolute URI, not a CURIE, unlike the raw JSON-LD `@context`). `path` for a
    `defs`-derived entry is relative to whatever property referenced that def, not the document
    root -- acceptable here since only `uri` drives the bblock_uris lookup this feeds; `path` is
    carried along purely for eyeballing/debugging, not resolved to be absolute.

    We don't need to walk `ref` pointers or reconstruct absolute paths: every `defs` group only
    ever exists because at least one `properties` entry (or another `defs` entry) points at it,
    so the union of every `effectiveId` found anywhere in `properties[]` and in every list under
    `defs{}.values()` already covers all bindings in the file, with no risk of missing one.
    """

    def _entries(items: list[dict]) -> list[tuple[str, str]]:
        pairs = []
        for item in items:
            uri = item.get("effectiveId")
            path = item.get("path")
            if uri and isinstance(path, list):
                pairs.append((".".join(str(segment) for segment in path), uri))
        return pairs

    pairs = _entries(resolved_properties_json.get("properties") or [])
    for group in (resolved_properties_json.get("defs") or {}).values():
        pairs.extend(_entries(group))
    return list(dict.fromkeys(pairs))  # de-dup identical (path, uri) pairs, preserve order


# Vocabulary-shaped but not real: examples routinely use these as illustrative subject/object
# IRIs (RFC 2606 reserved domains, plus the ubiquitous "http://example.org/..." convention). A
# predicate or rdf:type value under one of these is placeholder data, not a real semantic
# binding worth indexing -- it would only add lookup noise, since a caller querying bblock_uris
# for a genuine vocabulary term would never search for "example.org" in the first place.
_PLACEHOLDER_NAMESPACE_PREFIXES = (
    "http://example.org/",
    "https://example.org/",
    "http://example.com/",
    "https://example.com/",
    "http://example.net/",
    "https://example.net/",
    "http://example.edu/",
    "https://example.edu/",
)


def _is_placeholder_uri(uri: str) -> bool:
    return uri.startswith(_PLACEHOLDER_NAMESPACE_PREFIXES)


def _turtle_predicate_uris(ttl_text: str) -> list[str]:
    """Predicate URIs used anywhere in a Turtle example snippet, plus `rdf:type` *object* values
    (also vocabulary terms, just not predicates -- e.g. `a sosa:Observation`). Unlike
    `_resolved_property_bindings`'s `effectiveId`s, these describe terms a bblock's example data
    *uses*, not ones its schema *declares* -- see docs/06-semantic-binding-lookup-plan.md's
    "Example-derived bindings" for why that distinction matters for ranking. Best-effort: a
    malformed snippet is the register's own responsibility to keep valid (its CI checks this),
    not this crawler's -- logged and skipped, not fatal to the rest of the bblock.

    A Turtle predicate position is always a full IRI (`URIRef`), never a blank node or literal,
    so no separate blank-node filtering is needed there; `rdf:type`'s object, unlike a normal
    predicate's object, is restricted the same way here since it's semantically a class IRI, not
    arbitrary triple data.
    """
    graph = Graph()
    try:
        graph.parse(data=ttl_text, format="turtle")
    except Exception as exc:  # noqa: BLE001 - best-effort, matches this module's fetch handling
        logger.warning("Failed to parse Turtle example snippet: %s", exc)
        return []

    uris: list[str] = []
    for subject, predicate, obj in graph:
        if isinstance(predicate, URIRef) and not _is_placeholder_uri(str(predicate)):
            uris.append(str(predicate))
        if predicate == RDF.type and isinstance(obj, URIRef) and not _is_placeholder_uri(str(obj)):
            uris.append(str(obj))
    return list(dict.fromkeys(uris))  # de-dup, preserve first-seen order


def _example_bindings(json_full_doc: dict) -> list[tuple[str, str]]:
    """(path, uri) pairs scraped from each example's Turtle snippet (`language` "ttl" or
    "turtle"), if present -- already inlined as `code` text in `json_full_doc["examples"]`, no
    extra fetch needed (see `_bblock_usage_text`, which reads the same `examples` array for its
    JSON snippet). `path` here is `"example:<title>"` (or `"example:<index>"` for an untitled
    example), not a schema property path -- a Turtle triple has no notion of "the JSON Schema
    property this came from". The caller tags these `source="example"` (see
    `build_register_chunks`) to keep them distinguishable from declared (`source="schema"`)
    bindings for ranking purposes.
    """
    pairs: list[tuple[str, str]] = []
    for index, example in enumerate(json_full_doc.get("examples") or []):
        if not isinstance(example, dict):
            continue
        ttl_code = next(
            (
                snippet.get("code")
                for snippet in example.get("snippets") or []
                if isinstance(snippet, dict) and snippet.get("language") in ("ttl", "turtle") and snippet.get("code")
            ),
            None,
        )
        if not ttl_code:
            continue
        label = example.get("title") or str(index)
        pairs.extend((f"example:{label}", uri) for uri in _turtle_predicate_uris(ttl_code))
    return list(dict.fromkeys(pairs))  # de-dup identical (path, uri) pairs, preserve order


# rdflib format name for each `ontology` file extension the postprocessor auto-detects (see
# bblocks-authoring's "Ontology declaration": "ontology.ttl" or "ontology.owl"), plus ".rdf" for
# a bblock that names its resource explicitly rather than relying on auto-detection. Not
# exhaustive of every rdflib-supported serialization -- ontology files in this ecosystem are
# only ever Turtle or RDF/XML in practice, matching the two extensions the postprocessor itself
# auto-detects.
_ONTOLOGY_EXTENSION_FORMATS = {".ttl": "turtle", ".owl": "xml", ".rdf": "xml"}


def _ontology_format(url: str, content_type: str | None) -> str:
    """Picks the rdflib parser format for an `ontology` URL: the file extension first (covers
    the common case, including a URL with no discriminating Content-Type such as a raw GitHub
    file), falling back to sniffing the Content-Type header for the handful of registers that
    serve `ontology.owl` as RDF/XML without a recognizable extension. Defaults to "turtle" --
    the postprocessor's own auto-detection default -- when neither signal is conclusive, rather
    than raising before even trying to parse."""
    path = urlsplit(url).path.lower()
    for ext, fmt in _ONTOLOGY_EXTENSION_FORMATS.items():
        if path.endswith(ext):
            return fmt
    if content_type and "xml" in content_type.lower():
        return "xml"
    return "turtle"


def _ontology_subject_uris(rdf_text: str, rdf_format: str) -> list[str]:
    """Subject URIs of every triple in an ontology document -- the terms this bblock *defines*
    (a class, property, individual, ...), not the (mostly boilerplate, borrowed-vocabulary)
    predicates used to describe them. This is the mirror image of `_turtle_predicate_uris()`:
    an example's subjects are throwaway instance IRIs and its predicates are the vocabulary
    terms of interest, whereas an ontology's *subjects* are the vocabulary terms it mints and
    its predicates (`rdf:type`, `rdfs:label`, `owl:equivalentClass`, ...) are near-universally
    borrowed from well-known vocabularies and say nothing distinctive about this bblock. A blank
    node subject (e.g. an anonymous OWL restriction) isn't a vocabulary term with a URI of its
    own, so only `URIRef` subjects are collected. Best-effort, same as `_turtle_predicate_uris`:
    a malformed/unparseable document is logged and skipped, not fatal to the rest of the bblock.
    """
    graph = Graph()
    try:
        graph.parse(data=rdf_text, format=rdf_format)
    except Exception as exc:  # noqa: BLE001 - best-effort, matches this module's fetch handling
        logger.warning("Failed to parse ontology document (format=%s): %s", rdf_format, exc)
        return []

    uris: list[str] = []
    for subject in graph.subjects():
        if isinstance(subject, URIRef) and not _is_placeholder_uri(str(subject)):
            uris.append(str(subject))
    return list(dict.fromkeys(uris))  # de-dup, preserve first-seen order


def _ontology_bindings(rdf_text: str, rdf_format: str) -> list[tuple[str, str]]:
    """(path, uri) pairs for an ontology document's subject URIs, `path`-tagged `"ontology"` --
    unlike a schema binding or an example (each tied to a specific property/example), an
    ontology-defined term has no such anchor to carry along, so the constant label is purely
    informational, same spirit as `_example_bindings()`'s `"example:<title>"`."""
    return [("ontology", uri) for uri in _ontology_subject_uris(rdf_text, rdf_format)]


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
) -> tuple[list[Chunk], dict[str, str], list[str], dict[str, list[tuple[str, str, str]]]]:
    """Returns the chunks to embed, a bblock_id -> description map (sourced from the same
    json-full doc fetched below for the bblock_description chunk, not register.json -- which has
    no per-bblock description field) for the caller to also feed into the FTS5 keyword index, the
    ids of bblocks whose main (json-full) metadata failed to fetch -- the caller uses this to
    surface the register as having partial results rather than a silent full success -- and a
    bblock_id -> (path, uri, source) list map of semantic bindings for the caller to feed into
    the bblock_uris reverse index (see docs/06-semantic-binding-lookup-plan.md). `source` is
    "ontology" (the bblock's own ontology file), "schema" (resolvedSchemaProperties), or
    "example" (a Turtle example snippet). A bblock absent from this last map simply has none of
    those three, or none of them carry a semantic binding -- not an error case."""
    chunks: list[Chunk] = []
    descriptions: dict[str, str] = {}
    failed_bblock_ids: list[str] = []
    bindings: dict[str, list[tuple[str, str, str]]] = {}

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

        # Fetched whenever present, regardless of whether ldContext already produced schema_text
        # above -- resolvedSchemaProperties is the source of truth for bblock_uris bindings even
        # for a bblock that also has a perfectly good ldContext (see module docstring).
        resolved_json: dict | None = None
        resolved_url = raw_bblock.get("resolvedSchemaProperties")
        if resolved_url:
            try:
                fetched = await get_json(client, resolved_url)
            except Exception as exc:  # noqa: BLE001 - best-effort: skip this chunk/bindings, keep the bblock
                logger.warning(
                    "Failed to fetch resolvedSchemaProperties for %s from %s: %s", bblock_id, resolved_url, exc
                )
            else:
                if isinstance(fetched, dict):
                    resolved_json = fetched

        if not schema_text and resolved_json:
            schema_text = _resolved_properties_text(resolved_json)  # unchanged fallback behavior

        # `ontology` is a plain URL string on the raw bblock entry (register.json), unlike
        # `resolvedSchemaProperties`/`ldContext` -- no per-bblock json-full lookup needed to
        # find it. Not JSON, so fetched with get_text (Turtle or RDF/XML) rather than get_json.
        ontology_bindings: list[tuple[str, str]] = []
        ontology_url = raw_bblock.get("ontology")
        if ontology_url:
            try:
                ontology_text, content_type = await get_text(client, ontology_url)
            except Exception as exc:  # noqa: BLE001 - best-effort: skip these bindings, keep the bblock
                logger.warning("Failed to fetch ontology for %s from %s: %s", bblock_id, ontology_url, exc)
            else:
                ontology_bindings = _ontology_bindings(ontology_text, _ontology_format(ontology_url, content_type))

        bblock_bindings: list[tuple[str, str, str]] = [(path, uri, "ontology") for path, uri in ontology_bindings]
        if resolved_json:
            bblock_bindings.extend((path, uri, "schema") for path, uri in _resolved_property_bindings(resolved_json))
        bblock_bindings.extend((path, uri, "example") for path, uri in _example_bindings(json_full_doc))
        if bblock_bindings:
            bindings[bblock_id] = bblock_bindings

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

    return chunks, descriptions, failed_bblock_ids, bindings
