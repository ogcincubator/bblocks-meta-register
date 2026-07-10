INDEXER_VERSION = 2
"""Bump this whenever a change to app/crawler/indexer.py's extraction/transform logic (e.g.
_extract_presence, _extract_edges) would produce different stored data for a register whose
register.json `modified` timestamp hasn't changed -- otherwise needs_reindex() only compares
`modified` and would skip already-crawled registers forever, leaving stale data from the old
logic in place until upstream content happens to change. See CLAUDE.md for the bump procedure."""


def needs_reindex(stored_modified: str | None, fetched_modified: str | None, stored_indexer_version: int | None) -> bool:
    """Cheap register-level change detection: register.json's `modified` timestamp is bumped
    by the postprocessor on every run, so an equality check is enough to decide whether to
    skip re-fetching/re-indexing this register's bblocks -- unless the indexer's own code
    changed since this register was last indexed (INDEXER_VERSION mismatch), in which case
    reindex regardless of `modified`."""
    return stored_modified != fetched_modified or stored_indexer_version != INDEXER_VERSION