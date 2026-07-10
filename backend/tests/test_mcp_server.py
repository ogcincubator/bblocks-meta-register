from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.mcp.server as mcp_server
from app.repositories.bblocks import upsert_bblock
from app.repositories.deps import replace_bblock_deps
from tests.test_api_endpoints import _seed

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mcp_tools(db_engine, embedding_provider, monkeypatch):
    """Points app.mcp.server's session_scope/get_embedding_provider at the isolated test
    engine and fake provider, the same way api_client overrides FastAPI's dependencies --
    MCP tools call these directly rather than through Depends()."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)

    @asynccontextmanager
    async def fake_session_scope():
        async with factory() as session:
            yield session

    monkeypatch.setattr(mcp_server, "session_scope", fake_session_scope)
    monkeypatch.setattr(mcp_server, "get_embedding_provider", lambda: embedding_provider)
    return mcp_server


async def test_search_bblocks_tool(db_session, mcp_tools):
    await _seed(db_session)

    results = await mcp_tools.search_bblocks("bounding box")
    assert [r["id"] for r in results] == ["ogc.main.a"]
    assert "score" in results[0]


async def test_get_bblock_tool(db_session, mcp_tools):
    await _seed(db_session)

    detail = await mcp_tools.get_bblock("ogc.main.a")
    assert detail["has_schema"] is True
    assert detail["depends_on"] == []

    with pytest.raises(ValueError, match="not found"):
        await mcp_tools.get_bblock("does.not.exist")


async def test_get_bblocks_tool(db_session, mcp_tools):
    await _seed(db_session)

    body = await mcp_tools.get_bblocks(["ogc.main.a", "does.not.exist"])
    assert [item["id"] for item in body["items"]] == ["ogc.main.a"]
    assert body["items"][0]["depends_on"] == []
    assert body["not_found"] == ["does.not.exist"]


async def test_list_bblocks_tool(db_session, mcp_tools):
    await _seed(db_session)

    body = await mcp_tools.list_bblocks_tool(register="ogc/main")
    assert body["numberMatched"] == 1
    assert body["items"][0]["id"] == "ogc.main.a"


async def test_register_and_org_tools(db_session, mcp_tools):
    await _seed(db_session)

    register = await mcp_tools.get_register("ogc/main")
    assert [b["id"] for b in register["bblocks"]] == ["ogc.main.a"]

    registers = await mcp_tools.list_registers_tool(org="ogc")
    assert [r["id"] for r in registers] == ["ogc/main"]

    orgs = await mcp_tools.list_orgs_tool()
    assert [o["id"] for o in orgs] == ["ogc"]

    org = await mcp_tools.get_org("ogc")
    assert [r["id"] for r in org["registers"]] == ["ogc/main"]

    with pytest.raises(ValueError, match="not found"):
        await mcp_tools.get_register("does/not-exist")
    with pytest.raises(ValueError, match="not found"):
        await mcp_tools.get_org("does-not-exist")


async def test_bblock_dependencies_tool(db_session, mcp_tools):
    await _seed(db_session)
    await upsert_bblock(
        db_session,
        bblock_id="ogc.main.b",
        register_id="ogc/main",
        name="B",
        abstract=None,
        status=None,
        item_class="schema",
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
    await replace_bblock_deps(db_session, "ogc.main.a", [("ogc.main.b", "dependsOn")])
    await db_session.commit()

    graph = await mcp_tools.bblock_dependencies("ogc.main.a", direction="depends_on", depth=2)
    assert graph["depends_on"] == [[{"from": "ogc.main.a", "to": "ogc.main.b", "kind": "dependsOn"}]]

    graph = await mcp_tools.bblock_dependencies("ogc.main.b", direction="dependents", depth=1)
    assert graph["dependents"] == [[{"from": "ogc.main.b", "to": "ogc.main.a", "kind": "dependsOn"}]]

    with pytest.raises(ValueError, match="not found"):
        await mcp_tools.bblock_dependencies("does.not.exist")
