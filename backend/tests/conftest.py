import os

# Must happen before any `app.*` import: the crawl loop must not fire against the real
# meta-registry during tests, and the DB path must not point at a developer's real DB file.
os.environ["BBLOCKS_CRAWL_ON_STARTUP"] = "false"
os.environ["BBLOCKS_DATABASE_PATH"] = ":memory:"

import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import app.db.models  # noqa: E402,F401 - registers ORM tables on the shared metadata
import app.db.tables  # noqa: E402,F401 - registers Core tables on the shared metadata
from app.db.base import metadata  # noqa: E402


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def api_client(db_engine):
    """FastAPI TestClient equivalent for async apps: an httpx.AsyncClient bound to the app's
    ASGI callable, with the DB session dependency overridden to use the isolated test engine
    instead of the process-global one."""
    from app.api.deps import db_session as db_session_dep
    from app.main import app

    factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _override():
        async with factory() as session:
            yield session

    app.dependency_overrides[db_session_dep] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()
