"""Dependency edge queries -- plain Core statements against bblock_deps/register_deps.

No ORM relationship()s here on purpose: both tables allow a dangling target (the target
bblock/register may not be indexed yet, or ever). See app/db/tables.py.
"""

from sqlalchemy import Table, delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tables import bblock_deps, register_deps


async def replace_bblock_deps(
    session: AsyncSession, source_id: str, edges: list[tuple[str, str]]
) -> None:
    """Replace all outgoing edges for one bblock. `edges` is a list of (target_id, kind).

    Flushes first: unlike a `select()`, a Core `insert()`/`delete()` executed via
    `session.execute()` does not autoflush pending ORM adds, so a bblock upserted via
    upsert_bblock() just before this call wouldn't be visible yet -- tripping the FK on
    bblock_deps.source_id (see app/db/tables.py) even though the row is "already" added.
    """
    await session.flush()
    await session.execute(delete(bblock_deps).where(bblock_deps.c.source_id == source_id))
    if edges:
        await session.execute(
            insert(bblock_deps),
            [{"source_id": source_id, "target_id": target_id, "kind": kind} for target_id, kind in edges],
        )


async def outgoing_bblock_deps(session: AsyncSession, bblock_id: str) -> list[tuple[str, str]]:
    result = await session.execute(
        select(bblock_deps.c.target_id, bblock_deps.c.kind).where(bblock_deps.c.source_id == bblock_id)
    )
    return [(row.target_id, row.kind) for row in result]


async def incoming_bblock_deps(session: AsyncSession, bblock_id: str) -> list[tuple[str, str]]:
    result = await session.execute(
        select(bblock_deps.c.source_id, bblock_deps.c.kind).where(bblock_deps.c.target_id == bblock_id)
    )
    return [(row.source_id, row.kind) for row in result]


async def _traverse_self_join(
    session: AsyncSession,
    table: Table,
    from_col: str,
    to_col: str,
    start_id: str,
    depth: int,
) -> list[list[dict]]:
    """Multi-hop walk from start_id, `depth` hops deep, in a single query -- the direct edges
    in `table` are already fully materialized at crawl/index time (see the upsert helpers
    above), so this is walking that table, not re-deriving anything. Self-joins `table` to
    itself `depth` times (`depth`=2, the graph endpoints' default, is a plain two-level
    self-join) rather than issuing one query per level, let alone one per node.

    Each join is a LEFT JOIN so a chain shorter than `depth` (a node with no further
    dependencies) still surfaces its earlier levels, with later columns coming back NULL --
    detected below to stop that path early. A node with wide fan-out multiplies rows at every
    level it's joined through (row count grows roughly as fan-out^depth); acceptable at this
    catalog's scale (doc 03: "hundreds to low thousands" of items, `depth` capped at
    MAX_DEPENDENCY_DEPTH), but not a pattern to reach for on a much larger or denser graph.

    Cycles: there's no global "visited" set here (unlike a classic BFS), only per-level edge
    dedup (`seen[i]` below) -- so a cycle just gets re-walked on every remaining level instead
    of that depth budget going toward reaching new, farther-out nodes. Bounded and harmless
    (depth is capped, and duplicate edges across levels collapse in the caller/frontend, which
    key edges by (source, target, kind)), just less useful on a cyclic subgraph than a real BFS
    with a visited set would be. Trading that off for one query total instead of one per level
    (or per node) is the right call at this catalog's scale; revisit with a visited-set-based
    BFS (one query per level, pruning already-seen nodes from the next frontier) if traversal
    quality around cycles ever matters more than round-trip count.
    """
    aliases = [table.alias(f"lvl{i}") for i in range(depth)]
    columns = []
    for i, alias in enumerate(aliases):
        columns += [
            getattr(alias.c, from_col).label(f"from{i}"),
            getattr(alias.c, to_col).label(f"to{i}"),
            alias.c.kind.label(f"kind{i}"),
        ]

    query = select(*columns).select_from(aliases[0]).where(getattr(aliases[0].c, from_col) == start_id)
    for i in range(1, depth):
        query = query.outerjoin(aliases[i], getattr(aliases[i].c, from_col) == getattr(aliases[i - 1].c, to_col))

    rows = (await session.execute(query)).all()

    levels: list[list[dict]] = [[] for _ in range(depth)]
    seen: list[set[tuple[str, str, str]]] = [set() for _ in range(depth)]
    for row in rows:
        for i in range(depth):
            from_id, to_id, kind = row[3 * i], row[3 * i + 1], row[3 * i + 2]
            if from_id is None or to_id is None:
                break
            edge_key = (from_id, to_id, kind)
            if edge_key not in seen[i]:
                seen[i].add(edge_key)
                levels[i].append({"from": from_id, "to": to_id, "kind": kind})

    while levels and not levels[-1]:
        levels.pop()
    return levels


async def traverse_outgoing_bblock_deps(session: AsyncSession, start_id: str, depth: int) -> list[list[dict]]:
    return await _traverse_self_join(session, bblock_deps, "source_id", "target_id", start_id, depth)


async def traverse_incoming_bblock_deps(session: AsyncSession, start_id: str, depth: int) -> list[list[dict]]:
    return await _traverse_self_join(session, bblock_deps, "target_id", "source_id", start_id, depth)


async def replace_register_deps(
    session: AsyncSession, source_register_id: str, edges: set[tuple[str, str]]
) -> None:
    """Replace all outgoing register-level edges for one register (rolled up from bblock_deps
    by the indexer). `edges` is a set of (target_register_id, kind). Flushes first -- see
    replace_bblock_deps for why."""
    await session.flush()
    await session.execute(
        delete(register_deps).where(register_deps.c.source_register_id == source_register_id)
    )
    if edges:
        await session.execute(
            insert(register_deps),
            [
                {"source_register_id": source_register_id, "target_register_id": target_id, "kind": kind}
                for target_id, kind in edges
            ],
        )


async def outgoing_register_deps(session: AsyncSession, register_id: str) -> list[tuple[str, str]]:
    result = await session.execute(
        select(register_deps.c.target_register_id, register_deps.c.kind).where(
            register_deps.c.source_register_id == register_id
        )
    )
    return [(row.target_register_id, row.kind) for row in result]


async def incoming_register_deps(session: AsyncSession, register_id: str) -> list[tuple[str, str]]:
    result = await session.execute(
        select(register_deps.c.source_register_id, register_deps.c.kind).where(
            register_deps.c.target_register_id == register_id
        )
    )
    return [(row.source_register_id, row.kind) for row in result]


async def traverse_outgoing_register_deps(session: AsyncSession, start_id: str, depth: int) -> list[list[dict]]:
    return await _traverse_self_join(
        session, register_deps, "source_register_id", "target_register_id", start_id, depth
    )


async def traverse_incoming_register_deps(session: AsyncSession, start_id: str, depth: int) -> list[list[dict]]:
    return await _traverse_self_join(
        session, register_deps, "target_register_id", "source_register_id", start_id, depth
    )
