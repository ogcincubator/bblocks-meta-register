import pytest
from sqlalchemy import text

from app.repositories import bblock_uris as bblock_uris_repo
from app.repositories import bblocks as bblocks_repo
from app.repositories import conflicts as conflicts_repo
from app.repositories import crawl_status as crawl_status_repo
from app.repositories import deps as deps_repo
from app.repositories import orgs as orgs_repo
from app.repositories import registers as registers_repo

pytestmark = pytest.mark.asyncio


async def _seed_org_and_register(session, org_id="ogc", register_id="ogc/main"):
    await orgs_repo.upsert_org(
        session, org_id=org_id, name="OGC", description="desc", url="https://ogc.org", maintainers=[]
    )
    await registers_repo.upsert_register(
        session,
        register_id=register_id,
        org_id=org_id,
        name="main",
        register_url="https://example.org/register.json",
        viewer_url=None,
        description=None,
    )
    await registers_repo.set_register_modified(session, register_id, "2026-01-01T00:00:00Z")
    await session.commit()


async def test_org_upsert_and_get(db_session):
    await _seed_org_and_register(db_session)
    org = await orgs_repo.get_org(db_session, "ogc")
    assert org is not None
    assert org.name == "OGC"
    assert len(org.registers) == 1


async def test_register_change_detection_field(db_session):
    await _seed_org_and_register(db_session)
    modified = await registers_repo.get_register_modified(db_session, "ogc/main")
    assert modified == "2026-01-01T00:00:00Z"
    assert await registers_repo.get_register_modified(db_session, "missing/register") is None


async def test_register_reindex_state(db_session):
    from app.crawler.change_detection import INDEXER_VERSION

    await _seed_org_and_register(db_session)
    modified, indexer_version = await registers_repo.get_register_reindex_state(db_session, "ogc/main")
    assert modified == "2026-01-01T00:00:00Z"
    assert indexer_version == INDEXER_VERSION
    assert await registers_repo.get_register_reindex_state(db_session, "missing/register") == (None, None)


async def test_register_status_lifecycle(db_session):
    await _seed_org_and_register(db_session)
    register = await registers_repo.get_register(db_session, "ogc/main")
    assert register.status == "pending"

    await registers_repo.mark_register_crawling(db_session, "ogc/main")
    await db_session.commit()
    register = await registers_repo.get_register(db_session, "ogc/main")
    assert register.status == "crawling"

    await registers_repo.record_crawl_result(db_session, "ogc/main", status="ok")
    await db_session.commit()
    register = await registers_repo.get_register(db_session, "ogc/main")
    assert register.status == "ready"

    await registers_repo.mark_register_crawling(db_session, "ogc/main")
    await registers_repo.record_crawl_result(db_session, "ogc/main", status="error", error="boom")
    await db_session.commit()
    register = await registers_repo.get_register(db_session, "ogc/main")
    assert register.status == "failed"
    assert register.last_error == "boom"


async def test_delete_registers_not_in_cascades_bblocks(db_session):
    await _seed_org_and_register(db_session)
    await bblocks_repo.upsert_bblock(
        db_session,
        bblock_id="ogc.main.thing",
        register_id="ogc/main",
        name="Thing",
        abstract=None,
        status=None,
        item_class=None,
        version=None,
        tags=[],
        date_time_addition=None,
        date_of_last_change=None,
        has_schema=False,
        has_ld_context=False,
        has_shacl_shapes=False,
        schema_urls={},
        ld_context_url=None,
        shacl_shapes_urls=[],
        sources=[],
    )
    await db_session.commit()

    deleted = await registers_repo.delete_registers_not_in(db_session, keep_ids=set())
    await db_session.commit()
    assert deleted == ["ogc/main"]
    assert await bblocks_repo.get_bblock(db_session, "ogc.main.thing") is None


async def test_list_bblocks_filters_and_paging(db_session):
    await _seed_org_and_register(db_session)
    for i in range(3):
        await bblocks_repo.upsert_bblock(
            db_session,
            bblock_id=f"ogc.main.item{i}",
            register_id="ogc/main",
            name=f"Item {i}",
            abstract="a bounding box thing" if i == 0 else "something else",
            status=None,
            item_class="schema",
            version=None,
            tags=[],
            date_time_addition=None,
            date_of_last_change=None,
            has_schema=True,
            has_ld_context=False,
            has_shacl_shapes=False,
            schema_urls={"application/json": "https://example.org/schema.json"},
            ld_context_url=None,
            shacl_shapes_urls=[],
            sources=[],
        )
    await db_session.commit()

    items, total = await bblocks_repo.list_bblocks(db_session, limit=2, offset=0)
    assert total == 3
    assert len(items) == 2


async def test_bblock_deps_and_register_deps_roundtrip(db_session):
    await _seed_org_and_register(db_session)
    await bblocks_repo.upsert_bblock(
        db_session,
        bblock_id="ogc.main.a",
        register_id="ogc/main",
        name="A",
        abstract=None,
        status=None,
        item_class=None,
        version=None,
        tags=[],
        date_time_addition=None,
        date_of_last_change=None,
        has_schema=False,
        has_ld_context=False,
        has_shacl_shapes=False,
        schema_urls={},
        ld_context_url=None,
        shacl_shapes_urls=[],
        sources=[],
    )
    await deps_repo.replace_bblock_deps(db_session, "ogc.main.a", [("ogc.main.b", "dependsOn")])
    await db_session.commit()

    outgoing = await deps_repo.outgoing_bblock_deps(db_session, "ogc.main.a")
    assert outgoing == [("ogc.main.b", "dependsOn")]
    incoming = await deps_repo.incoming_bblock_deps(db_session, "ogc.main.b")
    assert incoming == [("ogc.main.a", "dependsOn")]

    await deps_repo.replace_register_deps(db_session, "ogc/main", {("acme/other", "dependsOn")})
    await db_session.commit()
    assert await deps_repo.outgoing_register_deps(db_session, "ogc/main") == [("acme/other", "dependsOn")]
    assert await deps_repo.incoming_register_deps(db_session, "acme/other") == [("ogc/main", "dependsOn")]


async def _seed_bblock(session, bblock_id, register_id="ogc/main"):
    await bblocks_repo.upsert_bblock(
        session,
        bblock_id=bblock_id,
        register_id=register_id,
        name=bblock_id,
        abstract=None,
        status=None,
        item_class=None,
        version=None,
        tags=[],
        date_time_addition=None,
        date_of_last_change=None,
        has_schema=False,
        has_ld_context=False,
        has_shacl_shapes=False,
        schema_urls={},
        ld_context_url=None,
        shacl_shapes_urls=[],
        sources=[],
    )


async def test_bblock_uris_replace_roundtrip(db_session):
    await _seed_org_and_register(db_session)
    await _seed_bblock(db_session, "ogc.main.a")
    await db_session.commit()

    await bblock_uris_repo.replace_bblock_uris(db_session, "ogc.main.a", [("lat", "http://example.org/ns/lat", "schema")])
    await db_session.commit()
    matches, total = await bblock_uris_repo.find_bblocks_by_uri(db_session, "http://example.org/ns/lat")
    assert total == 1
    assert matches[0].path == "lat"
    assert matches[0].match_type == "exact"
    assert matches[0].source == "schema"

    # A second call replaces the bblock's rows rather than appending to them.
    await bblock_uris_repo.replace_bblock_uris(db_session, "ogc.main.a", [("long", "http://example.org/ns/long", "schema")])
    await db_session.commit()
    _, total = await bblock_uris_repo.find_bblocks_by_uri(db_session, "http://example.org/ns/lat")
    assert total == 0
    matches, total = await bblock_uris_repo.find_bblocks_by_uri(db_session, "http://example.org/ns/long")
    assert total == 1
    assert matches[0].bblock_id == "ogc.main.a"


async def test_find_bblocks_by_uri_modes(db_session):
    await _seed_org_and_register(db_session)
    await _seed_bblock(db_session, "ogc.main.a")
    await _seed_bblock(db_session, "ogc.main.b")
    await db_session.commit()

    # b's URI is a strict extension of a's -- exercises the "exact sorts before prefix" ordering
    # invariant and the "exact" match_type still applying under mode="prefix" for a itself.
    await bblock_uris_repo.replace_bblock_uris(db_session, "ogc.main.a", [("prop", "http://example.org/ns/term", "schema")])
    await bblock_uris_repo.replace_bblock_uris(
        db_session, "ogc.main.b", [("prop", "http://example.org/ns/term/nested", "schema")]
    )
    await db_session.commit()

    exact, exact_total = await bblock_uris_repo.find_bblocks_by_uri(
        db_session, "http://example.org/ns/term", mode="exact"
    )
    assert exact_total == 1
    assert [(m.bblock_id, m.match_type) for m in exact] == [("ogc.main.a", "exact")]

    prefix, prefix_total = await bblock_uris_repo.find_bblocks_by_uri(
        db_session, "http://example.org/ns/term", mode="prefix"
    )
    assert prefix_total == 2
    assert {(m.bblock_id, m.match_type) for m in prefix} == {
        ("ogc.main.a", "exact"),
        ("ogc.main.b", "prefix"),
    }

    both, both_total = await bblock_uris_repo.find_bblocks_by_uri(
        db_session, "http://example.org/ns/term", mode="both"
    )
    assert both_total == 2
    # ORDER BY uri, bblock_id puts the shorter exact-matching uri ahead of its own extension.
    assert [m.bblock_id for m in both] == ["ogc.main.a", "ogc.main.b"]

    no_match, no_match_total = await bblock_uris_repo.find_bblocks_by_uri(
        db_session, "http://example.org/ns/unrelated", mode="both"
    )
    assert no_match_total == 0
    assert no_match == []


async def test_find_bblocks_by_uri_ranks_schema_source_before_example_at_same_match_type(db_session):
    """A declared (source="schema") binding should outrank an incidental (source="example",
    scraped from a Turtle example snippet) one when both tie on match_type -- see
    docs/06-semantic-binding-lookup-plan.md's "Example-derived bindings" addendum. Uses two
    exact-match rows on the *same* uri (from different bblocks) so match_type can't already
    explain the ordering by itself."""
    await _seed_org_and_register(db_session)
    await _seed_bblock(db_session, "ogc.main.example_only")
    await _seed_bblock(db_session, "ogc.main.schema")
    await db_session.commit()

    # Insert example-sourced first, to confirm ordering isn't just insertion order.
    await bblock_uris_repo.replace_bblock_uris(
        db_session, "ogc.main.example_only", [("example:Sample", "http://example.org/ns/term", "example")]
    )
    await bblock_uris_repo.replace_bblock_uris(
        db_session, "ogc.main.schema", [("prop", "http://example.org/ns/term", "schema")]
    )
    await db_session.commit()

    matches, total = await bblock_uris_repo.find_bblocks_by_uri(db_session, "http://example.org/ns/term")

    assert total == 2
    assert [(m.bblock_id, m.source) for m in matches] == [
        ("ogc.main.schema", "schema"),
        ("ogc.main.example_only", "example"),
    ]


async def test_find_bblocks_by_uri_prefix_is_boundary_anchored(db_session):
    """Regression test for the false-positive a plain string-prefix match would have: a uri
    that merely starts with the same characters as the query, but isn't nested under it at a
    '/' or '#' boundary, must not be returned. See _prefix_conditions()'s docstring."""
    await _seed_org_and_register(db_session)
    await _seed_bblock(db_session, "ogc.main.nested")
    await _seed_bblock(db_session, "ogc.main.sibling")
    await db_session.commit()

    # Genuinely nested under the "http://example.org/ns/term" namespace...
    await bblock_uris_repo.replace_bblock_uris(
        db_session, "ogc.main.nested", [("prop", "http://example.org/ns/term/child", "schema")]
    )
    # ...vs. merely sharing the same leading characters, with no separator in between -- a
    # different term entirely, not a member of the "term" namespace.
    await bblock_uris_repo.replace_bblock_uris(
        db_session, "ogc.main.sibling", [("prop", "http://example.org/ns/termOther", "schema")]
    )
    await db_session.commit()

    matches, total = await bblock_uris_repo.find_bblocks_by_uri(
        db_session, "http://example.org/ns/term", mode="prefix"
    )
    assert total == 1
    assert [m.bblock_id for m in matches] == ["ogc.main.nested"]

    # A query with (or without) a trailing separator must behave identically -- both should
    # still exclude the sibling and include the genuinely-nested child.
    matches, total = await bblock_uris_repo.find_bblocks_by_uri(
        db_session, "http://example.org/ns/term/", mode="prefix"
    )
    assert total == 1
    assert [m.bblock_id for m in matches] == ["ogc.main.nested"]


async def test_bblock_uris_cascade_deleted_with_register(db_session):
    await _seed_org_and_register(db_session)
    await _seed_bblock(db_session, "ogc.main.a")
    await db_session.commit()
    await bblock_uris_repo.replace_bblock_uris(db_session, "ogc.main.a", [("prop", "http://example.org/ns/term", "schema")])
    await db_session.commit()

    _, total = await bblock_uris_repo.find_bblocks_by_uri(db_session, "http://example.org/ns/term")
    assert total == 1

    await bblocks_repo.delete_bblocks_for_register(db_session, "ogc/main")
    await db_session.commit()

    _, total = await bblock_uris_repo.find_bblocks_by_uri(db_session, "http://example.org/ns/term")
    assert total == 0


async def test_find_bblocks_by_uri_prefix_query_uses_index(db_session):
    """Confirms find_bblocks_by_uri's prefix query actually uses the `uri` index with EXPLAIN
    QUERY PLAN rather than trusting a general claim blindly -- see
    docs/06-semantic-binding-lookup-plan.md's "Prefix-match query strategy".

    Two things were checked this way and both failed the first, more "obvious" approach:
    1. A plain `LIKE 'prefix%'` scan only used the index once `PRAGMA case_sensitive_like=ON`
       was set, which app/db/base.py doesn't set -- replaced with a `>=`/`<` range scan instead,
       which needs no such pragma.
    2. That range scan alone still matched a false positive like "http://x/abc" for prefix
       "http://x/a" (see test_find_bblocks_by_uri_prefix_is_boundary_anchored) -- fixed by
       anchoring the range to a '/' or '#' boundary (_prefix_conditions()), which ORs together
       three conditions on the same `uri` column. This test confirms that OR still resolves to
       index searches (SQLite's "MULTI-INDEX OR" plan) rather than falling back to a scan.
    """
    await _seed_org_and_register(db_session)
    await _seed_bblock(db_session, "ogc.main.a")
    await db_session.commit()
    await bblock_uris_repo.replace_bblock_uris(db_session, "ogc.main.a", [("prop", "http://example.org/ns/term", "schema")])
    await db_session.commit()

    plan = await db_session.execute(
        text(
            "EXPLAIN QUERY PLAN SELECT * FROM bblock_uris "
            "WHERE uri = :self "
            "   OR (uri >= :slash_lo AND uri < :slash_hi) "
            "   OR (uri >= :hash_lo AND uri < :hash_hi)"
        ),
        {
            "self": "http://example.org/ns/term",
            "slash_lo": "http://example.org/ns/term/",
            "slash_hi": "http://example.org/ns/term0",
            "hash_lo": "http://example.org/ns/term#",
            "hash_hi": "http://example.org/ns/term$",
        },
    )
    plan_text = " ".join(str(row) for row in plan.fetchall())
    assert "ix_bblock_uris_uri" in plan_text
    assert "MULTI-INDEX OR" in plan_text


async def test_identifier_conflicts_record_and_list(db_session):
    await _seed_org_and_register(db_session)
    await conflicts_repo.record_conflict(
        db_session, conflicting_id="ogc.main.a", existing_register_id="ogc/main", attempted_register_id="acme/other"
    )
    await db_session.commit()
    conflicts = await conflicts_repo.list_conflicts(db_session)
    assert len(conflicts) == 1
    assert conflicts[0]["conflicting_id"] == "ogc.main.a"


async def test_crawl_status_start_and_finish(db_session):
    run_id = await crawl_status_repo.start_run(db_session, register_id="ogc/main")
    await db_session.commit()
    await crawl_status_repo.finish_run(db_session, run_id, status="ok")
    await db_session.commit()
    runs = await crawl_status_repo.list_recent_runs(db_session)
    assert runs[0]["status"] == "ok"
    latest = await crawl_status_repo.latest_run_per_register(db_session)
    assert latest["ogc/main"]["id"] == run_id
