import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import MetaData, event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import StaticPool

from app.config import settings


def _ensure_database_directory(database_path: str) -> None:
    """Create the parent directory of a file-based SQLite path if it doesn't exist yet, so a
    fresh checkout doesn't need a manual `mkdir` before the first run."""
    if database_path == ":memory:":
        return
    parent = Path(database_path).parent
    if str(parent) not in ("", "."):
        parent.mkdir(parents=True, exist_ok=True)


_ensure_database_directory(settings.database_path)

# Single MetaData shared by the ORM models (app/db/models.py) and the plain Core tables
# (app/db/tables.py) so Alembic autogenerate sees both when diffing.
metadata = MetaData()


class Base(DeclarativeBase):
    metadata = metadata


def _make_engine(database_url: str) -> AsyncEngine:
    # StaticPool always, not just for the in-memory test DB: SQLAlchemy's default pool for a
    # file-based aiosqlite URL is a 5-connection AsyncAdaptedQueuePool, which handed each
    # concurrent crawler task (see app/crawler/orchestrator.py's worker pool) a *different*
    # SQLite connection. A row inserted-but-uncommitted on one connection isn't visible to
    # another, so a bblock's own row and its just-inserted bblock_deps edges could end up on
    # different connections and trip the FK check. docs/02-viewer-application.md's "single
    # writer path" design assumes one aiosqlite connection (one background thread) for all
    # writes; StaticPool is what actually delivers that -- an in-memory URL needs it for a
    # different reason (each checkout would otherwise open a fresh, empty database).
    engine = create_async_engine(
        database_url, connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


engine: AsyncEngine = _make_engine(settings.database_url)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)

# StaticPool hands out the *same* underlying DBAPI connection to every session -- it avoids
# opening new connections, but doesn't serialize concurrent use of that one connection. Two
# sessions with overlapping open transactions on it is exactly what produced the FK
# violations seen when the crawler's worker pool ran several registers' writes concurrently
# (see app/crawler/orchestrator.py): statements from different sessions could interleave on
# the one connection instead of each transaction running start-to-finish in isolation. This
# lock makes "checkout a session, use it, close it" atomic app-wide. It also serializes API
# reads behind any in-progress crawl write, trading away WAL's concurrent-readers benefit --
# an acceptable simplification at this catalog's scale (see docs/03-indexing-and-search.md);
# splitting into a dedicated single-connection writer engine plus a multi-connection reader
# pool would restore concurrent reads if this ever becomes a bottleneck.
_db_lock = asyncio.Lock()


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    async with _db_lock, async_session_factory() as session:
        yield session


async def get_session() -> AsyncIterator[AsyncSession]:
    async with _db_lock, async_session_factory() as session:
        yield session
