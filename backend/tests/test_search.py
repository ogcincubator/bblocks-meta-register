import httpx
import pytest
import respx

from app.crawler.discovery import RegisterInfo
from app.search import keyword_index, vector_store
from app.search.chunking import build_register_chunks
from app.search.service import hybrid_search
from app.search.vector_store import Chunk

pytestmark = pytest.mark.asyncio


# --- vector_store -----------------------------------------------------------------------


async def test_vector_store_upsert_search_and_filter(db_session):
    chunks = [
        Chunk(
            key="bblock_core:b1",
            text="x",
            chunk_type="bblock_core",
            org="ogc",
            register_url="https://x/r1.json",
            bblock_id="b1",
            item_class="schema",
        ),
        Chunk(
            key="bblock_core:b2",
            text="x",
            chunk_type="bblock_core",
            org="ogc",
            register_url="https://x/r2.json",
            bblock_id="b2",
            item_class="datatype",
        ),
    ]
    await vector_store.upsert_chunks(db_session, chunks, [[1.0, 0.0, 0.0, 0.0], [0.9, 0.1, 0.0, 0.0]])
    await db_session.commit()

    results = await vector_store.search(db_session, [1.0, 0.0, 0.0, 0.0], 5, org="ogc")
    assert {r.bblock_id for r in results} == {"b1", "b2"}

    results = await vector_store.search(db_session, [1.0, 0.0, 0.0, 0.0], 5, org="ogc", item_class="datatype")
    assert [r.bblock_id for r in results] == ["b2"]


async def test_vector_store_upsert_is_idempotent_and_delete_by_register_scopes_correctly(db_session):
    chunk = Chunk(
        key="bblock_core:b1", text="x", chunk_type="bblock_core", org="ogc",
        register_url="https://x/r1.json", bblock_id="b1",
    )
    await vector_store.upsert_chunks(db_session, [chunk], [[1.0, 0.0, 0.0, 0.0]])
    await vector_store.upsert_chunks(db_session, [chunk], [[0.0, 1.0, 0.0, 0.0]])  # re-upsert, same key
    await db_session.commit()

    results = await vector_store.search(db_session, [0.0, 1.0, 0.0, 0.0], 5, org="ogc")
    assert len(results) == 1  # not duplicated

    await vector_store.delete_by_register(db_session, "https://x/r2.json")  # different register
    await db_session.commit()
    assert len(await vector_store.search(db_session, [0.0, 1.0, 0.0, 0.0], 5, org="ogc")) == 1

    await vector_store.delete_by_register(db_session, "https://x/r1.json")
    await db_session.commit()
    assert await vector_store.search(db_session, [0.0, 1.0, 0.0, 0.0], 5, org="ogc") == []


# --- keyword_index -----------------------------------------------------------------------


async def test_keyword_index_search_and_filters(db_session):
    await keyword_index.upsert(
        db_session, bblock_id="b1", register_id="ogc/main", org="ogc", item_class="schema",
        status="valid", name="Feature Property Set", abstract="a propertyset for features", tags=["features"],
    )
    await keyword_index.upsert(
        db_session, bblock_id="b2", register_id="acme/other", org="acme", item_class="datatype",
        status="valid", name="Unrelated thing", abstract="nothing to do with it", tags=[],
    )
    await db_session.commit()

    assert [h.bblock_id for h in await keyword_index.search(db_session, "feature", 10)] == ["b1"]
    assert await keyword_index.search(db_session, "feature", 10, org="acme") == []


async def test_keyword_index_sanitizes_special_characters(db_session):
    await keyword_index.upsert(
        db_session, bblock_id="b1", register_id="ogc/main", org="ogc", item_class=None,
        status=None, name="Feature", abstract=None, tags=[],
    )
    await db_session.commit()

    # A raw FTS5 syntax error (mismatched quote, bare operator) must not raise.
    assert await keyword_index.search(db_session, 'weird: query* -syntax "here', 10) == []


async def test_keyword_index_delete_by_register(db_session):
    await keyword_index.upsert(
        db_session, bblock_id="b1", register_id="ogc/main", org="ogc", item_class=None,
        status=None, name="Feature", abstract=None, tags=[],
    )
    await db_session.commit()

    await keyword_index.delete_by_register(db_session, "ogc/main")
    await db_session.commit()
    assert await keyword_index.search(db_session, "feature", 10) == []


# --- hybrid_search -----------------------------------------------------------------------


async def test_hybrid_search_merges_keyword_and_semantic_and_ranks_keyword_hit_first(
    db_session, embedding_provider
):
    # Keyword-only match: text mentions "sensor" (FTS) but the fake embedding for its own
    # abstract won't fire the "geo"/"feature" vector dimensions the query uses.
    await keyword_index.upsert(
        db_session, bblock_id="kw-only", register_id="ogc/main", org="ogc", item_class=None,
        status=None, name="Sensor thing", abstract="a sensor observation", tags=[],
    )
    # Semantic-only match: no FTS row, but its core chunk text contains "geo feature".
    await vector_store.upsert_chunks(
        db_session,
        [Chunk(
            key="bblock_core:sem-only", text="a geo feature", chunk_type="bblock_core",
            org="ogc", register_url="https://x/r.json", bblock_id="sem-only",
        )],
        await embedding_provider.embed_documents(["a geo feature"]),
    )
    await db_session.commit()

    hits, total = await hybrid_search(db_session, embedding_provider, "geo feature", org="ogc", limit=10)
    assert total == 1
    assert [h.bblock_id for h in hits] == ["sem-only"]
    assert hits[0].matched_chunk_types == ["bblock_core"]


async def test_hybrid_search_weights_semantic_higher_than_keyword_by_default(db_session, embedding_provider):
    # Both bblocks match "geo" via FTS equally; only "geo-and-feature" also has a chunk whose
    # fake embedding fires the "geo"/"feature" query dimensions -- default (non-strict) merging
    # should rank it above the keyword-only-equivalent match because semantic dominates the sum.
    await keyword_index.upsert(
        db_session, bblock_id="kw-equal-1", register_id="ogc/main", org="ogc", item_class=None,
        status=None, name="geo", abstract="geo", tags=[],
    )
    await keyword_index.upsert(
        db_session, bblock_id="geo-and-feature", register_id="ogc/main", org="ogc", item_class=None,
        status=None, name="geo", abstract="geo", tags=[],
    )
    await vector_store.upsert_chunks(
        db_session,
        [Chunk(
            key="bblock_core:geo-and-feature", text="a geo feature", chunk_type="bblock_core",
            org="ogc", register_url="https://x/r.json", bblock_id="geo-and-feature",
        )],
        await embedding_provider.embed_documents(["a geo feature"]),
    )
    await db_session.commit()

    hits, total = await hybrid_search(db_session, embedding_provider, "geo", org="ogc", limit=10)
    assert total == 2
    assert [h.bblock_id for h in hits] == ["geo-and-feature", "kw-equal-1"]


async def test_hybrid_search_strict_skips_semantic_pass_entirely(db_session, embedding_provider):
    await keyword_index.upsert(
        db_session, bblock_id="kw-only", register_id="ogc/main", org="ogc", item_class=None,
        status=None, name="Sensor thing", abstract="a sensor observation", tags=[],
    )
    await vector_store.upsert_chunks(
        db_session,
        [Chunk(
            key="bblock_core:sem-only", text="a geo feature", chunk_type="bblock_core",
            org="ogc", register_url="https://x/r.json", bblock_id="sem-only",
        )],
        await embedding_provider.embed_documents(["a geo feature"]),
    )
    await db_session.commit()

    hits, total = await hybrid_search(
        db_session, embedding_provider, "geo feature", org="ogc", limit=10, strict=True
    )
    assert total == 0  # keyword pass requires every token; neither is in kw-only's indexed text

    hits, total = await hybrid_search(db_session, embedding_provider, "sensor", org="ogc", limit=10, strict=True)
    assert [h.bblock_id for h in hits] == ["kw-only"]
    assert hits[0].matched_chunk_types == []


async def test_hybrid_search_applies_filters_before_merge(db_session, embedding_provider):
    await keyword_index.upsert(
        db_session, bblock_id="b1", register_id="ogc/main", org="ogc", item_class="schema",
        status=None, name="Feature", abstract="a geo feature", tags=[],
    )
    await keyword_index.upsert(
        db_session, bblock_id="b2", register_id="acme/other", org="acme", item_class="schema",
        status=None, name="Feature", abstract="a geo feature", tags=[],
    )
    await db_session.commit()

    hits, total = await hybrid_search(db_session, embedding_provider, "feature", org="ogc", limit=10)
    assert total == 1
    assert hits[0].bblock_id == "b1"


# --- chunking ---------------------------------------------------------------------------


REGISTER_INFO = RegisterInfo(register_id="ogc/main", org_id="ogc", name="main", register_url="https://x/r.json")


@respx.mock
async def test_build_register_chunks_fetches_ld_context_and_examples():
    respx.get("https://x/context.jsonld").mock(
        return_value=httpx.Response(200, json={"@context": {"myProp": "myNamespace:myProp", "@version": 1.1}})
    )
    respx.get("https://x/doc.json").mock(
        return_value=httpx.Response(
            200,
            json={"examples": [{"title": "Example 1", "snippets": [{"language": "json", "code": '{"a": 1}'}]}]},
        )
    )
    register_json = {
        "name": "Main",
        "abstract": "abstract",
        "bblocks": [
            {
                "itemIdentifier": "ogc.main.a",
                "name": "A",
                "abstract": "a thing",
                "itemClass": "schema",
                "ldContext": "https://x/context.jsonld",
                "documentation": {"json-full": {"url": "https://x/doc.json"}},
            }
        ],
    }

    async with httpx.AsyncClient() as client:
        chunks = await build_register_chunks(client, REGISTER_INFO, register_json)

    by_type = {c.chunk_type: c for c in chunks}
    assert set(by_type) == {"register_summary", "bblock_core", "bblock_schema", "bblock_examples"}
    assert "myProp: myNamespace:myProp" in by_type["bblock_schema"].text
    assert "@version" not in by_type["bblock_schema"].text
    assert "Example 1" in by_type["bblock_examples"].text
    assert '"a": 1' in by_type["bblock_examples"].text


@respx.mock
async def test_build_register_chunks_falls_back_to_resolved_properties_without_ld_context():
    respx.get("https://x/resolved.json").mock(
        return_value=httpx.Response(
            200,
            json={"properties": [{"path": ["a"]}, {"path": ["a", "b"]}, {"path": []}]},
        )
    )
    register_json = {
        "bblocks": [
            {
                "itemIdentifier": "ogc.main.a",
                "name": "A",
                "resolvedSchemaProperties": "https://x/resolved.json",
            }
        ]
    }

    async with httpx.AsyncClient() as client:
        chunks = await build_register_chunks(client, REGISTER_INFO, register_json)

    schema_chunk = next(c for c in chunks if c.chunk_type == "bblock_schema")
    assert schema_chunk.text == "a\na.b"


@respx.mock
async def test_build_register_chunks_skips_failed_fetch_without_raising():
    respx.get("https://x/context.jsonld").mock(return_value=httpx.Response(500))
    register_json = {
        "bblocks": [
            {"itemIdentifier": "ogc.main.a", "name": "A", "ldContext": "https://x/context.jsonld"},
        ]
    }

    async with httpx.AsyncClient() as client:
        chunks = await build_register_chunks(client, REGISTER_INFO, register_json)

    assert [c.chunk_type for c in chunks] == ["bblock_core"]
