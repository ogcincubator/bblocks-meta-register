import asyncio

import pytest

from app.crawler.discovery import RegisterInfo
from app.crawler.indexer import index_register
from app.repositories.orgs import upsert_org

pytestmark = pytest.mark.asyncio


async def _seed(db_session):
    await upsert_org(
        db_session, org_id="ogc", name="OGC", description="desc", url="https://ogc.org", maintainers=[]
    )
    from app.repositories.registers import upsert_register

    await upsert_register(
        db_session,
        register_id="ogc/main",
        org_id="ogc",
        name="main",
        register_url="https://example.org/register.json",
        viewer_url="https://example.org/viewer/",
        description="Main register",
        modified="2026-01-01T00:00:00Z",
    )
    register_info = RegisterInfo(register_id="ogc/main", org_id="ogc", name="main", register_url="https://example.org/register.json")
    await index_register(
        db_session,
        register_info,
        {
            "name": "Main",
            "modified": "2026-01-01T00:00:00Z",
            "bblocks": [
                {
                    "itemIdentifier": "ogc.main.a",
                    "name": "A",
                    "abstract": "a bounding box thing",
                    "itemClass": "schema",
                    "schema": {"application/json": "https://example.org/schema.json"},
                }
            ],
        },
    )
    await db_session.commit()


async def test_orgs_endpoints(db_session, api_client):
    await _seed(db_session)

    response = await api_client.get("/orgs")
    assert response.status_code == 200
    assert [org["id"] for org in response.json()] == ["ogc"]

    response = await api_client.get("/orgs/ogc")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "OGC"
    assert [r["id"] for r in body["registers"]] == ["ogc/main"]

    response = await api_client.get("/orgs/missing")
    assert response.status_code == 404


async def test_registers_endpoints(db_session, api_client):
    await _seed(db_session)

    response = await api_client.get("/registers", params={"org": "ogc"})
    assert response.status_code == 200
    assert [r["id"] for r in response.json()] == ["ogc/main"]

    response = await api_client.get("/registers/ogc/main")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Main"
    assert [b["id"] for b in body["bblocks"]] == ["ogc.main.a"]


async def test_bblocks_endpoints(db_session, api_client):
    await _seed(db_session)

    response = await api_client.get("/bblocks", params={"q": "bounding box"})
    assert response.status_code == 200
    body = response.json()
    assert body["numberMatched"] == 1
    assert body["items"][0]["id"] == "ogc.main.a"

    response = await api_client.get("/bblocks/ogc.main.a")
    assert response.status_code == 200
    assert response.json()["has_schema"] is True

    response = await api_client.get("/bblocks/does.not.exist")
    assert response.status_code == 404


async def test_admin_status_and_reindex(api_client, monkeypatch):
    response = await api_client.get("/admin/status")
    assert response.status_code == 200
    assert response.json() == {"recent_runs": [], "latest_per_register": {}}

    response = await api_client.get("/admin/conflicts")
    assert response.status_code == 200
    assert response.json() == {"conflicts": []}

    # The endpoint just needs to fire a background task and return immediately -- the actual
    # crawl behavior (network + the process-global DB engine) is covered by the indexer/repo
    # tests above, not by hitting the real meta-registry from a unit test.
    triggered = {}

    async def fake_run_crawl_cycle(only_register_id=None):
        triggered["only_register_id"] = only_register_id

    monkeypatch.setattr("app.api.admin.run_crawl_cycle", fake_run_crawl_cycle)

    response = await api_client.post("/admin/reindex", params={"register": "ogc/main"})
    assert response.status_code == 200
    assert response.json() == {"accepted": True, "register_id": "ogc/main"}

    await asyncio.sleep(0)  # let the fire-and-forget task run once before asserting
    assert triggered == {"only_register_id": "ogc/main"}


async def test_admin_requires_key_when_configured(api_client, monkeypatch):
    monkeypatch.setattr("app.api.deps.settings.admin_api_key", "s3cr3t")

    response = await api_client.get("/admin/status")
    assert response.status_code == 401

    response = await api_client.get("/admin/status", headers={"X-Admin-Api-Key": "wrong"})
    assert response.status_code == 401

    response = await api_client.get("/admin/status", headers={"X-Admin-Api-Key": "s3cr3t"})
    assert response.status_code == 200
