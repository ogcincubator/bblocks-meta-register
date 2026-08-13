"""Semantic-binding reverse index (`bblock_uris`): which bblock(s) bind a schema property to a
given RDF/vocabulary URI, or to any term under a URI prefix. See
docs/06-semantic-binding-lookup-plan.md for the design and the source of the (path, uri) pairs
this module stores (app/search/chunking.py's `_resolved_property_bindings()`).

No ORM model here, same reasoning as app/repositories/deps.py's bblock_deps/register_deps: this
is plain insert/query over a Core table, no relationship() traversal needed.
"""

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import and_, case, delete, func, insert, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tables import bblock_uris

# Below this, a "prefix" query risks a near-full-table scan (e.g. a bare "http://" would match
# almost everything) for little practical benefit -- a real vocabulary namespace prefix is
# comfortably longer than this in practice. Enforced by callers (API/MCP layer), not here.
MIN_PREFIX_LENGTH = 8


@dataclass(frozen=True)
class UriMatch:
    bblock_id: str
    uri: str
    # Dot-joined property path (e.g. "location.lat"), already flattened by
    # chunking._resolved_property_bindings() -- not re-split back into segments here, since
    # that would be a lossy round-trip for any segment that itself contains a literal ".".
    # "example:<title>" for a source="example" row instead (see chunking._example_bindings()).
    path: str | None
    match_type: Literal["exact", "prefix"]
    # "schema" (declared via resolvedSchemaProperties) or "example" (scraped from a Turtle
    # example snippet) -- see chunking.py's module docstring. Used as a ranking tiebreaker in
    # find_bblocks_by_uri: a declared binding outranks an incidental one at the same match_type.
    source: Literal["schema", "example"]


async def replace_bblock_uris(session: AsyncSession, bblock_id: str, bindings: list[tuple[str, str, str]]) -> None:
    """(path, uri, source) triples -- path already dot-joined by the caller (see UriMatch.path).
    Mirrors replace_bblock_deps()'s delete-then-insert shape, including the flush-first
    requirement: a bblock upserted just before this call in the same session wouldn't otherwise
    be visible yet to the FK check on bblock_uris.bblock_id (see replace_bblock_deps)."""
    await session.flush()
    await session.execute(delete(bblock_uris).where(bblock_uris.c.bblock_id == bblock_id))
    if bindings:
        await session.execute(
            insert(bblock_uris),
            [{"bblock_id": bblock_id, "path": path, "uri": uri, "source": source} for path, uri, source in bindings],
        )


# Separator -> the character immediately after it in code-point order, used to turn "everything
# starting with the literal string `norm + sep`" into a plain >=/< range with no LIKE/regex:
# under lexicographic (BINARY) ordering, the set of strings starting with a given literal prefix
# P is exactly the half-open interval [P, P_upper), where P_upper is P with its very last
# character bumped to the next code point -- anything starting with P but continuing with more
# characters after that point still sorts *before* P_upper (its first len(P) characters equal P,
# which is < P_upper's), and P_upper itself is the smallest string that's NOT >= every extension
# of P. E.g. for P = ".../ns/" (sep="/", next_char="0", since chr(ord("/")+1) == "0"): every
# ".../ns/xyz" satisfies ".../ns/" <= uri < ".../ns0", because comparison stops at the "/" vs "0"
# character (both strings agree up to ".../ns", then "/" (0x2F) < "0" (0x30) settles it
# regardless of what follows) -- while ".../nsX" for any other X is excluded, since it never even
# reaches the ">= .../ns/" bound in the first place unless X == "/" itself.
_BOUNDARY_NEXT_CHAR: dict[str, str] = {"/": "0", "#": "$"}


def _normalize_prefix(uri: str) -> str:
    """Strips a single trailing '/' or '#' from a prefix-mode query input, so "http://x/ns" and
    "http://x/ns/" (or ".../ns#") are treated identically -- callers shouldn't have to know
    whether the stored, boundary-anchored form expects one or not."""
    if uri and uri[-1] in _BOUNDARY_NEXT_CHAR:
        return uri[:-1]
    return uri


def _prefix_conditions(uri: str, *, include_self: bool):
    """Boundary-anchored prefix match: a row counts as a match only if its `uri` *is* the
    (normalized) prefix itself, or continues immediately after a '/' or '#' right after it -- not
    merely any `uri` that happens to start with the same characters. This fixes a false-positive
    a plain string-prefix range (or `LIKE 'prefix%'`) has: querying prefix "http://x/a" would
    otherwise also match "http://x/abc", which isn't nested under "http://x/a" as a namespace at
    all, just a coincidentally-shared substring.

    Expressed as `>=`/`<` range comparisons (one pair per boundary character) rather than a
    regex or a materialized table of precomputed prefixes -- verified via EXPLAIN QUERY PLAN
    that SQLite still uses `ix_bblock_uris_uri` for this, through its "OR optimization" (query
    plan reports `MULTI-INDEX OR`, one index SEARCH per branch) -- see
    tests/test_repositories.py and docs/06-semantic-binding-lookup-plan.md's "Prefix-match query
    strategy".

    `include_self=False` skips the "uri == prefix itself" branch -- used for mode="both", where
    the caller already has a separate exact-match condition on the raw (un-normalized) input;
    including it again here would just be a redundant OR branch, not a behavior difference.
    """
    norm = _normalize_prefix(uri)
    conditions = [bblock_uris.c.uri == norm] if include_self else []
    for sep, next_char in _BOUNDARY_NEXT_CHAR.items():
        conditions.append(and_(bblock_uris.c.uri >= norm + sep, bblock_uris.c.uri < norm + next_char))
    return or_(*conditions)


def _match_conditions(uri: str, mode: Literal["exact", "prefix", "both"]):
    conditions = []
    if mode in ("exact", "both"):
        conditions.append(bblock_uris.c.uri == uri)
    if mode == "prefix":
        conditions.append(_prefix_conditions(uri, include_self=True))
    elif mode == "both":
        conditions.append(_prefix_conditions(uri, include_self=False))
    return or_(*conditions)


async def find_bblocks_by_uri(
    session: AsyncSession,
    uri: str,
    *,
    mode: Literal["exact", "prefix", "both"] = "both",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[UriMatch], int]:
    """Exact and/or prefix lookup against bblock_uris.uri. Returns (page of matches, total
    matching count) -- same (items, total) shape as app.repositories.bblocks.list_bblocks, so
    the API layer can populate BblockListResponse's numberMatched/numberReturned distinction
    the same way it does for every other bblock-listing endpoint.

    Ordering: `ORDER BY (uri = :uri) DESC, (source = 'schema') DESC, uri, bblock_id` -- two
    explicit ranking keys ahead of the plain lexical tiebreak:

    1. Exact before prefix. Every row that matches only the boundary-anchored prefix condition
       necessarily has `uri` as a strict, longer extension of the (normalized) input `uri`
       string, so this key doesn't strictly need to be spelled out (lexical `uri` order alone
       would already put every exact match first "for free" -- see git history for the
       single-key version this replaced). It's kept explicit now that a second key exists,
       since relying on that lexicographic side effect once source-based ordering is also in
       play would be too easy to break by accident.
    2. A declared binding (`source = "schema"`) outranks an incidental one (`source = "example"`,
       scraped from a Turtle example snippet -- see chunking.py's `_example_bindings()`) among
       rows tied on the first key. A caller asking for the top N bblocks bound to a URI should
       see the ones that actually declare the binding before the ones that merely use the term
       in sample data.

    See docs/06-semantic-binding-lookup-plan.md's "Result ordering" / "Example-derived bindings"
    for the motivation (deterministic pagination; exact/declared hits not getting pushed past
    `limit` by a popular namespace's prefix or example hits). `match_type` is always based on
    actual uri == :uri equality, regardless of which `mode` was requested -- e.g. a mode="prefix"
    query still labels a row equal to the input value "exact".
    """
    where_clause = _match_conditions(uri, mode)

    total = (
        await session.execute(select(func.count()).select_from(bblock_uris).where(where_clause))
    ).scalar_one()

    order_by = (
        case((bblock_uris.c.uri == uri, 1), else_=0).desc(),
        case((bblock_uris.c.source == "schema", 1), else_=0).desc(),
        bblock_uris.c.uri,
        bblock_uris.c.bblock_id,
    )
    stmt = (
        select(bblock_uris.c.bblock_id, bblock_uris.c.uri, bblock_uris.c.path, bblock_uris.c.source)
        .where(where_clause)
        .order_by(*order_by)
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(stmt)
    matches = [
        UriMatch(
            bblock_id=row.bblock_id,
            uri=row.uri,
            path=row.path,
            match_type="exact" if row.uri == uri else "prefix",
            source=row.source,
        )
        for row in result
    ]
    return matches, total
