from app.crawler.change_detection import needs_reindex
from app.crawler.discovery import Discovery, OrgInfo, RegisterInfo, _parse_registers
from app.crawler.indexer import index_register
from app.crawler.orphans import cleanup_orphans
from app.repositories.bblocks import get_bblock
from app.repositories.conflicts import list_conflicts
from app.repositories.deps import outgoing_bblock_deps, outgoing_register_deps
from app.repositories.orgs import upsert_org
from app.repositories.registers import get_register, set_register_modified, upsert_register


def make_register_json(*bblocks: dict, modified: str = "2026-01-01T00:00:00Z") -> dict:
    return {"name": "Main", "abstract": "desc", "modified": modified, "viewerURL": None, "bblocks": list(bblocks)}


def test_parse_registers_skips_non_alias_keys():
    raw = {
        "default": "https://example.org/register.json",
        "@ogc/main": "https://example.org/ogc-main/register.json",
    }
    registers = _parse_registers(raw)
    assert len(registers) == 1
    assert registers[0].register_id == "ogc/main"
    assert registers[0].org_id == "ogc"
    assert registers[0].name == "main"


def test_needs_reindex():
    assert needs_reindex(None, "2026-01-01T00:00:00Z") is True
    assert needs_reindex("2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z") is False
    assert needs_reindex("2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z") is True


async def _seed_register(session, register_id="ogc/main", org_id="ogc"):
    await upsert_org(session, org_id=org_id, name=org_id, description=None, url=None, maintainers=[])
    await session.commit()


async def test_index_register_full_replace_and_presence_flags(db_session):
    await _seed_register(db_session)
    register_info = RegisterInfo(register_id="ogc/main", org_id="ogc", name="main", register_url="https://x/r.json")

    register_json = make_register_json(
        {
            "itemIdentifier": "ogc.main.a",
            "name": "A",
            "schema": {"application/json": "https://x/schema.json"},
            "ldContext": "https://x/context.jsonld",
            "shaclShapes": {},
            "dependsOn": ["ogc.main.b"],
        }
    )
    await index_register(db_session, register_info, register_json)
    await db_session.commit()

    bblock = await get_bblock(db_session, "ogc.main.a")
    assert bblock is not None
    assert bblock.has_schema is True
    assert bblock.has_ld_context is True
    assert bblock.has_shacl_shapes is False
    assert await outgoing_bblock_deps(db_session, "ogc.main.a") == [("ogc.main.b", "dependsOn")]

    # Re-index with a different bblock set: the old one must be gone (full replace).
    register_json_v2 = make_register_json(
        {"itemIdentifier": "ogc.main.c", "name": "C"}, modified="2026-02-01T00:00:00Z"
    )
    await index_register(db_session, register_info, register_json_v2)
    await db_session.commit()

    assert await get_bblock(db_session, "ogc.main.a") is None
    assert await get_bblock(db_session, "ogc.main.c") is not None

    # index_register() itself must never advance `modified` -- only set_register_modified()
    # does, once the caller confirms the *whole* crawl pipeline (including search-content
    # indexing) succeeded. Otherwise a failure after index_register() but before search
    # content is written would be wrongly treated as "already up to date" on the next crawl.
    register = await get_register(db_session, "ogc/main")
    assert register.modified is None


async def test_set_register_modified_advances_change_detection_field(db_session):
    await _seed_register(db_session)
    register_info = RegisterInfo(register_id="ogc/main", org_id="ogc", name="main", register_url="https://x/r.json")
    await index_register(db_session, register_info, make_register_json())
    await db_session.commit()

    register = await get_register(db_session, "ogc/main")
    assert register.modified is None

    await set_register_modified(db_session, "ogc/main", "2026-01-01T00:00:00Z")
    await db_session.commit()

    register = await get_register(db_session, "ogc/main")
    assert register.modified == "2026-01-01T00:00:00Z"


async def test_index_register_rejects_identifier_conflict(db_session):
    await _seed_register(db_session, register_id="ogc/main")
    await upsert_org(db_session, org_id="acme", name="acme", description=None, url=None, maintainers=[])
    await upsert_register(
        db_session,
        register_id="acme/other",
        org_id="acme",
        name="other",
        register_url="https://acme/r.json",
        viewer_url=None,
        description=None,
    )
    await db_session.commit()

    owner_info = RegisterInfo(register_id="ogc/main", org_id="ogc", name="main", register_url="https://x/r.json")
    await index_register(db_session, owner_info, make_register_json({"itemIdentifier": "shared.id", "name": "A"}))
    await db_session.commit()

    challenger_info = RegisterInfo(
        register_id="acme/other", org_id="acme", name="other", register_url="https://acme/r.json"
    )
    await index_register(
        db_session, challenger_info, make_register_json({"itemIdentifier": "shared.id", "name": "B"})
    )
    await db_session.commit()

    # The original owner's bblock is untouched; the conflict is recorded, not silently overwritten.
    bblock = await get_bblock(db_session, "shared.id")
    assert bblock.register_id == "ogc/main"
    assert bblock.name == "A"
    conflicts = await list_conflicts(db_session)
    assert len(conflicts) == 1
    assert conflicts[0]["existing_register_id"] == "ogc/main"
    assert conflicts[0]["attempted_register_id"] == "acme/other"


async def test_index_register_rolls_up_register_deps(db_session):
    await _seed_register(db_session, register_id="ogc/main")
    await upsert_org(db_session, org_id="acme", name="acme", description=None, url=None, maintainers=[])
    await upsert_register(
        db_session,
        register_id="acme/other",
        org_id="acme",
        name="other",
        register_url="https://acme/r.json",
        viewer_url=None,
        description=None,
    )
    await db_session.commit()

    other_info = RegisterInfo(register_id="acme/other", org_id="acme", name="other", register_url="https://acme/r.json")
    await index_register(db_session, other_info, make_register_json({"itemIdentifier": "acme.other.x", "name": "X"}))
    await db_session.commit()

    main_info = RegisterInfo(register_id="ogc/main", org_id="ogc", name="main", register_url="https://x/r.json")
    await index_register(
        db_session,
        main_info,
        make_register_json({"itemIdentifier": "ogc.main.a", "name": "A", "dependsOn": ["acme.other.x"]}),
    )
    await db_session.commit()

    assert await outgoing_register_deps(db_session, "ogc/main") == [("acme/other", "dependsOn")]


async def test_cleanup_orphans_removes_delisted_register(db_session):
    await _seed_register(db_session, register_id="ogc/main")
    register_info = RegisterInfo(register_id="ogc/main", org_id="ogc", name="main", register_url="https://x/r.json")
    await index_register(db_session, register_info, make_register_json({"itemIdentifier": "ogc.main.a", "name": "A"}))
    await db_session.commit()

    discovery = Discovery(orgs=[OrgInfo(org_id="ogc", name="ogc", description=None, url=None, maintainers=[])], registers=[])
    deleted = await cleanup_orphans(db_session, discovery)
    await db_session.commit()

    assert deleted["deleted_registers"] == ["ogc/main"]
    assert await get_bblock(db_session, "ogc.main.a") is None
    assert await get_register(db_session, "ogc/main") is None
