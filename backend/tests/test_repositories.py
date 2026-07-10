import pytest

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
