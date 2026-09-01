INDEXER_VERSION = 5
"""Bump this whenever a change to app/crawler/indexer.py's extraction/transform logic (e.g.
_extract_presence, _extract_edges) would produce different stored data for a register whose
register.json `modified` timestamp hasn't changed -- otherwise needs_reindex() only compares
`modified` and would skip already-crawled registers forever, leaving stale data from the old
logic in place until upstream content happens to change. See CLAUDE.md for the bump procedure.

3: app/search/chunking.py now also populates bblock_uris (semantic binding reverse index) from
resolvedSchemaProperties -- see docs/06-semantic-binding-lookup-plan.md. This lives in the
search-content half of the pipeline, not indexer.py's relational extraction, but needs_reindex()
gates the whole per-register pipeline (see orchestrator.py's _crawl_one_register), so the bump
rule still applies.

4: bblock_uris rows now also come from each example's Turtle snippet (source="example",
alongside the existing source="schema" rows) -- see chunking.py's _example_bindings(). Every
already-crawled register's stored bblock_uris.source defaults to "schema" via the 0006 migration
regardless of whether that row was actually schema- or example-derived, so a full reindex is
needed to backfill it correctly, not just to pick up the new example-derived rows themselves.

5: bblock_uris rows now also come from a bblock's own `ontology` file, if any (source="ontology"
-- the highest-ranked tier, ahead of "schema" and "example") -- see chunking.py's
_ontology_bindings()/docs/06's "Ontology-derived bindings" addendum. A full reindex is needed to
populate these new rows; there's no backfill-correctness concern this time (unlike bump 4)
since "ontology" is a brand new value, not a reinterpretation of an existing default."""


def needs_reindex(stored_modified: str | None, fetched_modified: str | None, stored_indexer_version: int | None) -> bool:
    """Cheap register-level change detection: register.json's `modified` timestamp is bumped
    by the postprocessor on every run, so an equality check is enough to decide whether to
    skip re-fetching/re-indexing this register's bblocks -- unless the indexer's own code
    changed since this register was last indexed (INDEXER_VERSION mismatch), in which case
    reindex regardless of `modified`."""
    return stored_modified != fetched_modified or stored_indexer_version != INDEXER_VERSION