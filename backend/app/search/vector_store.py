"""sqlite-vec-backed VectorStore (docs/03-indexing-and-search.md's `VectorStore` interface),
storing chunk embeddings plus the filtering metadata columns (`org`, `register_url`,
`item_class`, `status`) needed for correct top-K filtering -- see that doc's "Chunking
strategy" section for why those columns must live in the vector index itself rather than be
joined in afterwards.

`org`/`register_url` are declared as vec0 "partition key" columns (sharded, cheap equality
pre-filter before the KNN scan); `chunk_type`/`bblock_id`/`item_class`/`status` are plain
metadata columns, still applied during the scan (not a post-hoc join) but without the
partition-key sharding optimization -- appropriate for lower-cardinality/optional filters at
this catalog's scale (hundreds to low thousands of chunks, per doc 03).

sqlite-vec has no native upsert -- `upsert()` deletes any existing rows at the same rowids
first, matching the crawler's full-replace-per-register convention (see indexer.py).
"""

import hashlib
from dataclasses import dataclass

import sqlite_vec
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

VECTOR_TABLE = "vector_chunks"

# vec0 TEXT metadata columns reject NULL outright -- optional fields (bblock_id for a
# register_summary chunk, item_class/status for chunks whose owner doesn't have one) are
# stored as "" and translated back to None at the read boundary instead.
_NULL_SENTINEL = ""


@dataclass(frozen=True)
class Chunk:
    # Stable across reindexing the same bblock/register, e.g. "bblock_core:ogc.foo.bar" --
    # hashed into the integer rowid vec0 requires.
    key: str
    text: str
    chunk_type: str
    org: str
    register_url: str
    bblock_id: str | None = None
    item_class: str | None = None
    status: str | None = None


@dataclass(frozen=True)
class ChunkResult:
    rowid: int
    distance: float
    chunk_type: str
    bblock_id: str | None
    register_url: str


def rowid_for(key: str) -> int:
    """Deterministic positive 63-bit int from a chunk key -- stable across process restarts,
    unlike Python's salted str hash()."""
    digest = hashlib.sha1(key.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFFFFFFFFFFFFFF


def create_vector_table(conn, dimensions: int | None = None) -> None:
    """Sync helper for use inside Alembic migrations / test setup (raw DBAPI connection, not an
    AsyncSession) -- vec0 virtual tables aren't representable as SQLAlchemy Core metadata."""
    dim = dimensions or settings.embedding_dimensions
    conn.execute(
        f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS {VECTOR_TABLE} USING vec0(
            embedding float[{dim}] distance_metric=cosine,
            org text partition key,
            register_url text partition key,
            chunk_type text,
            bblock_id text,
            item_class text,
            status text
        )
        """
    )


async def upsert_chunks(session: AsyncSession, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
    if not chunks:
        return
    rowids = [rowid_for(chunk.key) for chunk in chunks]
    await session.execute(
        text(f"DELETE FROM {VECTOR_TABLE} WHERE rowid IN :rowids").bindparams(
            bindparam("rowids", expanding=True)
        ),
        {"rowids": rowids},
    )
    for chunk, rowid, embedding in zip(chunks, rowids, embeddings, strict=True):
        await session.execute(
            text(
                f"""
                INSERT INTO {VECTOR_TABLE}
                    (rowid, embedding, org, register_url, chunk_type, bblock_id, item_class, status)
                VALUES
                    (:rowid, :embedding, :org, :register_url, :chunk_type, :bblock_id, :item_class, :status)
                """
            ),
            {
                "rowid": rowid,
                "embedding": _serialize(embedding),
                "org": chunk.org,
                "register_url": chunk.register_url,
                "chunk_type": chunk.chunk_type,
                "bblock_id": chunk.bblock_id or _NULL_SENTINEL,
                "item_class": chunk.item_class or _NULL_SENTINEL,
                "status": chunk.status or _NULL_SENTINEL,
            },
        )


async def delete_by_register(session: AsyncSession, register_url: str) -> None:
    await session.execute(
        text(f"DELETE FROM {VECTOR_TABLE} WHERE register_url = :register_url"),
        {"register_url": register_url},
    )


async def search(
    session: AsyncSession,
    embedding: list[float],
    n: int,
    *,
    chunk_types: list[str] | None = None,
    org: str | None = None,
    register_url: str | None = None,
    item_class: str | None = None,
    status: str | None = None,
) -> list[ChunkResult]:
    conditions = ["embedding MATCH :embedding", "k = :k"]
    params: dict = {"embedding": _serialize(embedding), "k": n}

    if org is not None:
        conditions.append("org = :org")
        params["org"] = org
    if register_url is not None:
        conditions.append("register_url = :register_url")
        params["register_url"] = register_url
    if item_class is not None:
        conditions.append("item_class = :item_class")
        params["item_class"] = item_class
    if status is not None:
        conditions.append("status = :status")
        params["status"] = status

    stmt = text(
        f"""
        SELECT rowid, distance, chunk_type, bblock_id, register_url
        FROM {VECTOR_TABLE}
        WHERE {' AND '.join(conditions)}
        {"AND chunk_type IN :chunk_types" if chunk_types else ""}
        ORDER BY distance
        """
    )
    if chunk_types:
        stmt = stmt.bindparams(bindparam("chunk_types", expanding=True))
        params["chunk_types"] = chunk_types

    result = await session.execute(stmt, params)
    return [
        ChunkResult(
            rowid=row.rowid,
            distance=row.distance,
            chunk_type=row.chunk_type,
            bblock_id=row.bblock_id or None,
            register_url=row.register_url,
        )
        for row in result
    ]


def _serialize(embedding: list[float]) -> bytes:
    return sqlite_vec.serialize_float32(embedding)
