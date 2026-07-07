"""FTS5-backed keyword index over bblocks (docs/03-indexing-and-search.md's "keyword pass":
exact-ish matches on name/abstract/tags/itemIdentifier that embeddings are typically weak at).

Not an "external content" FTS5 table synced via triggers off the `bblocks` table, because
`bblocks.id` is a TEXT primary key and FTS5 external-content tables require an integer rowid
matching the content table's rowid. Simpler to keep this a standalone FTS5 table kept in sync
explicitly at the same two points the crawler already fully replaces a register's bblocks
(`delete_bblocks_for_register` / `upsert_bblock` in app/repositories/bblocks.py) -- same
full-replace-per-register convention as the vector store (see vector_store.py).
"""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

FTS_TABLE = "bblocks_fts"


@dataclass(frozen=True)
class KeywordHit:
    bblock_id: str
    score: float  # bm25(): more negative = better match


def create_fts_table(conn) -> None:
    """Sync helper for use inside Alembic migrations / test setup (raw DBAPI connection)."""
    conn.execute(
        f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS {FTS_TABLE} USING fts5(
            bblock_id UNINDEXED,
            register_id UNINDEXED,
            org UNINDEXED,
            item_class UNINDEXED,
            status UNINDEXED,
            name,
            abstract,
            tags,
            item_identifier
        )
        """
    )


async def upsert(
    session: AsyncSession,
    *,
    bblock_id: str,
    register_id: str,
    org: str,
    item_class: str | None,
    status: str | None,
    name: str,
    abstract: str | None,
    tags: list[str],
) -> None:
    await session.execute(
        text(f"DELETE FROM {FTS_TABLE} WHERE bblock_id = :bblock_id"), {"bblock_id": bblock_id}
    )
    await session.execute(
        text(
            f"""
            INSERT INTO {FTS_TABLE}
                (bblock_id, register_id, org, item_class, status, name, abstract, tags, item_identifier)
            VALUES
                (:bblock_id, :register_id, :org, :item_class, :status, :name, :abstract, :tags, :item_identifier)
            """
        ),
        {
            "bblock_id": bblock_id,
            "register_id": register_id,
            "org": org,
            "item_class": item_class or "",
            "status": status or "",
            "name": name,
            "abstract": abstract or "",
            "tags": " ".join(tags),
            "item_identifier": bblock_id,
        },
    )


async def delete_by_register(session: AsyncSession, register_id: str) -> None:
    await session.execute(text(f"DELETE FROM {FTS_TABLE} WHERE register_id = :register_id"), {"register_id": register_id})


def _sanitize_query(query: str) -> str:
    """FTS5's query syntax treats `"`, `*`, `:`, `-`, etc. specially -- a raw user search string
    containing any of them would otherwise raise a syntax error instead of just not matching.
    Quoting each token as a phrase disables that syntax; adjacent quoted phrases still default
    to an implicit AND, matching doc 03's "exact-ish matches" framing for this pass."""
    tokens = query.split()
    return " ".join('"' + token.replace('"', '""') + '"' for token in tokens)


async def search(
    session: AsyncSession,
    query: str,
    n: int,
    *,
    org: str | None = None,
    register_id: str | None = None,
    item_class: str | None = None,
    status: str | None = None,
) -> list[KeywordHit]:
    sanitized = _sanitize_query(query)
    if not sanitized:
        return []

    conditions = [f"{FTS_TABLE} MATCH :query"]
    params: dict = {"query": sanitized, "n": n}
    if org is not None:
        conditions.append("org = :org")
        params["org"] = org
    if register_id is not None:
        conditions.append("register_id = :register_id")
        params["register_id"] = register_id
    if item_class is not None:
        conditions.append("item_class = :item_class")
        params["item_class"] = item_class
    if status is not None:
        conditions.append("status = :status")
        params["status"] = status

    result = await session.execute(
        text(
            f"""
            SELECT bblock_id, bm25({FTS_TABLE}) AS score
            FROM {FTS_TABLE}
            WHERE {' AND '.join(conditions)}
            ORDER BY score
            LIMIT :n
            """
        ),
        params,
    )
    return [KeywordHit(bblock_id=row.bblock_id, score=row.score) for row in result]
