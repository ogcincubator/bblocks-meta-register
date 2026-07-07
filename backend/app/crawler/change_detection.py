def needs_reindex(stored_modified: str | None, fetched_modified: str | None) -> bool:
    """Cheap register-level change detection: register.json's `modified` timestamp is bumped
    by the postprocessor on every run, so an equality check is enough to decide whether to
    skip re-fetching/re-indexing this register's bblocks."""
    return stored_modified != fetched_modified
