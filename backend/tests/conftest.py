import os

# Must happen before any `app.*` import: the crawl loop must not fire against the real
# meta-registry during tests, and the DB path must not point at a developer's real DB file.
os.environ["BBLOCKS_CRAWL_ON_STARTUP"] = "false"
os.environ["BBLOCKS_DATABASE_PATH"] = ":memory:"

import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker  # noqa: E402

import app.db.models  # noqa: E402,F401 - registers ORM tables on the shared metadata
import app.db.tables  # noqa: E402,F401 - registers Core tables on the shared metadata
from app.db.base import _make_engine, metadata  # noqa: E402
from app.search.keyword_index import create_fts_table  # noqa: E402
from app.search.vector_store import create_vector_table  # noqa: E402


class FakeEmbeddingProvider:
    """Deterministic 4-dim stand-in for OllamaEmbeddingProvider -- tests need a real Ollama
    instance reachable for the actual provider, which isn't available in CI/offline runs.
    Dimension must match db_engine's create_vector_table(dimensions=4) below. Vectors are a
    crude bag-of-keywords so semantically related fixture text still ranks sensibly in tests
    that check ordering, not just presence."""

    _KEYWORDS = ("geo", "feature", "sensor", "unrelated")

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        lowered = text.lower()
        return [1.0 if keyword in lowered else 0.0 for keyword in self._KEYWORDS]


@pytest_asyncio.fixture
async def db_engine():
    # _make_engine (not a bare create_async_engine) -- tests need the same sqlite-vec
    # extension loading as the real app engine, since vector_store/keyword_index virtual
    # tables aren't part of SQLAlchemy's `metadata` and are created explicitly below.
    engine = _make_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
        await conn.run_sync(lambda c: create_vector_table(c.connection.dbapi_connection, dimensions=4))
        await conn.run_sync(lambda c: create_fts_table(c.connection.dbapi_connection))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
def embedding_provider():
    return FakeEmbeddingProvider()


@pytest_asyncio.fixture
async def api_client(db_engine, embedding_provider):
    """FastAPI TestClient equivalent for async apps: an httpx.AsyncClient bound to the app's
    ASGI callable, with the DB session and embedding provider dependencies overridden to use
    the isolated test engine / a network-free fake instead of the process-global ones."""
    from app.api.deps import db_session as db_session_dep
    from app.main import app
    from app.search.embeddings import get_embedding_provider

    factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[db_session_dep] = _override_session
    app.dependency_overrides[get_embedding_provider] = lambda: embedding_provider
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()
