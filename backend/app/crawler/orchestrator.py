"""Ties discovery, per-register fetch/change-detection/indexing, and orphan cleanup into one
crawl cycle. Concurrency is bounded at the register level (a fixed-size worker pool) since the
win comes from overlapping I/O-bound fetches to *different* hosts; per-host throttling is a
separate, lower-level concern (see app/crawler/http.py). A fetch/parse failure for one
register is logged and skipped, never allowed to abort the whole cycle -- it's picked up
again on the next scheduled run.
"""

import asyncio
import logging

from app.config import settings
from app.crawler.change_detection import needs_reindex
from app.crawler.discovery import Discovery, RegisterInfo, discover
from app.crawler.http import make_client
from app.crawler.indexer import build_search_content, index_register, write_search_content
from app.crawler.orphans import cleanup_orphans
from app.crawler.register_fetch import fetch_register
from app.db.base import session_scope
from app.repositories.crawl_status import finish_run, start_run
from app.repositories.orgs import upsert_org
from app.repositories.registers import get_register_modified, record_crawl_result, set_register_modified
from app.search.embeddings import get_embedding_provider

logger = logging.getLogger(__name__)


async def _crawl_one_register(client, semaphore: asyncio.Semaphore, register_info: RegisterInfo) -> None:
    async with semaphore:
        async with session_scope() as session:
            run_id = await start_run(session, register_id=register_info.register_id)
            await session.commit()

        try:
            logger.info("Crawling register %s (%s)", register_info.register_id, register_info.register_url)
            register_json = await fetch_register(client, register_info.register_url)

            async with session_scope() as session:
                stored_modified = await get_register_modified(session, register_info.register_id)
                fetched_modified = register_json.get("modified")

                if not needs_reindex(stored_modified, fetched_modified):
                    logger.info("Register %s unchanged, skipping reindex", register_info.register_id)
                    await record_crawl_result(session, register_info.register_id, status="ok")
                    await finish_run(session, run_id, status="skipped")
                    await session.commit()
                    return

                indexed_ids = await index_register(session, register_info, register_json)
                await session.commit()

            # Chunk-building and embedding are slow network calls (register content fetches,
            # Ollama) -- done outside session_scope() so they don't hold the app-wide _db_lock
            # (app/db/base.py) and block unrelated API reads for their duration.
            chunks, embeddings, accepted_bblocks = await build_search_content(
                client, get_embedding_provider(), register_info, register_json, indexed_ids
            )

            async with session_scope() as session:
                await write_search_content(session, register_info, chunks, embeddings, accepted_bblocks)
                # Only advance the change-detection field once the whole pipeline (relational
                # rows above + search content just written) has succeeded -- see
                # set_register_modified() for why this can't happen inside index_register().
                await set_register_modified(session, register_info.register_id, fetched_modified)
                await record_crawl_result(session, register_info.register_id, status="ok")
                await finish_run(session, run_id, status="ok")
                await session.commit()
        except Exception as exc:  # noqa: BLE001 - failure isolation: log+skip, never abort the cycle
            logger.exception("Failed to crawl register %s", register_info.register_id)
            async with session_scope() as session:
                await record_crawl_result(session, register_info.register_id, status="error", error=str(exc))
                await finish_run(session, run_id, status="error", error=str(exc))
                await session.commit()


async def run_crawl_cycle(only_register_id: str | None = None) -> None:
    async with session_scope() as session:
        cycle_run_id = await start_run(session, register_id=None)
        await session.commit()

    try:
        async with make_client() as client:
            discovery: Discovery = await discover(client)

        async with session_scope() as session:
            for org in discovery.orgs:
                await upsert_org(
                    session,
                    org_id=org.org_id,
                    name=org.name,
                    description=org.description,
                    url=org.url,
                    maintainers=org.maintainers,
                )
            await session.commit()

        registers = discovery.registers
        if only_register_id is not None:
            registers = [r for r in registers if r.register_id == only_register_id]

        semaphore = asyncio.Semaphore(settings.crawl_worker_pool_size)
        async with make_client() as client:
            await asyncio.gather(*(_crawl_one_register(client, semaphore, r) for r in registers))

        if only_register_id is None:
            # Orphan cleanup only makes sense on a full cycle -- a scoped reindex of one
            # register says nothing about whether other registers were removed upstream.
            async with session_scope() as session:
                deleted = await cleanup_orphans(session, discovery)
                await session.commit()
            if deleted["deleted_registers"] or deleted["deleted_orgs"]:
                logger.info("Orphan cleanup removed: %s", deleted)

        async with session_scope() as session:
            await finish_run(session, cycle_run_id, status="ok")
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Crawl cycle failed")
        async with session_scope() as session:
            await finish_run(session, cycle_run_id, status="error", error=str(exc))
            await session.commit()
