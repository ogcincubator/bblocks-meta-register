import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import sqlite_vec
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


def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

    # sqlite-vec ships as a loadable extension, not a Python-side implementation -- every
    # connection needs it loaded before any vec0 virtual table (search/vector_store.py) is
    # touched. `enable_load_extension`/`load_extension` are awaitable-only on aiosqlite's
    # driver connection, hence `run_async` (SQLAlchemy's documented pattern for calling
    # async-only driver methods from a sync pool event handler) instead of calling them
    # directly on the sync-looking `dbapi_connection` adapter. Load/unload immediately
    # around it rather than leaving extension loading enabled for the connection's
    # lifetime, since that's an unnecessary attack surface.
    async def _load_sqlite_vec(raw_connection):
        await raw_connection.enable_load_extension(True)
        await raw_connection.load_extension(sqlite_vec.loadable_path())
        await raw_connection.enable_load_extension(False)

    dbapi_connection.run_async(_load_sqlite_vec)


def _make_engine(database_url: str, *, poolclass=StaticPool) -> AsyncEngine:
    # StaticPool for the writer engine (below) always, not just for the in-memory test DB:
    # SQLAlchemy's default pool for a file-based aiosqlite URL is a 5-connection
    # AsyncAdaptedQueuePool, which handed each concurrent crawler task (see
    # app/crawler/orchestrator.py's worker pool) a *different* SQLite connection. A row
    # inserted-but-uncommitted on one connection isn't visible to another, so a bblock's own
    # row and its just-inserted bblock_deps edges could end up on different connections and
    # trip the FK check. docs/02-viewer-application.md's "single writer path" design assumes
    # one aiosqlite connection (one background thread) for all writes; StaticPool is what
    # actually delivers that -- an in-memory URL needs it for a different reason (each
    # checkout would otherwise open a fresh, empty database).
    engine = create_async_engine(database_url, connect_args={"check_same_thread": False}, poolclass=poolclass)
    event.listens_for(engine.sync_engine, "connect")(_set_sqlite_pragma)
    return engine


engine: AsyncEngine = _make_engine(settings.database_url)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)

# Two sessions with overlapping open write transactions on the *same* connection is what
# produced the FK violations seen when the crawler's worker pool ran several registers'
# writes concurrently (see app/crawler/orchestrator.py): statements from different sessions
# could interleave on that one connection instead of each transaction running start-to-finish
# in isolation. This lock makes "checkout a writer session, use it, close it" atomic
# app-wide -- but it only guards `engine`/`session_scope()` (the crawler's write path).
_db_lock = asyncio.Lock()

# `read_engine` is a *separate* multi-connection pool onto the same WAL-mode database file:
# WAL lets readers see a consistent last-committed snapshot without blocking on (or being
# blocked by) the writer, so API reads (SessionDep -> get_session(), all read-only per
# docs/02-viewer-application.md) don't need to queue behind _db_lock at all -- they were only
# doing so before because get_session() shared the single locked writer connection. An
# in-memory URL has no on-disk file for a second pool to open, so it falls back to sharing the
# one writer engine (only exercised by tests, which override this dependency directly anyway).
read_engine: AsyncEngine = engine if settings.database_path == ":memory:" else _make_engine(
    settings.database_url, poolclass=None
)
read_session_factory = async_sessionmaker(read_engine, expire_on_commit=False)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    async with _db_lock, async_session_factory() as session:
        yield session


async def get_session() -> AsyncIterator[AsyncSession]:
    async with read_session_factory() as session:
        yield session
