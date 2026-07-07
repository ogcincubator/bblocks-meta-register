"""Background crawl scheduling.

A trivial asyncio loop, deliberately not a cron-style scheduler: the requirement is "start
the next cycle N seconds after the previous one *finishes*," which a sleep-after-run loop
gives for free. A fixed-interval trigger (e.g. APScheduler's IntervalTrigger) fires at fixed
wall-clock offsets from a start time and would need extra coalesce/misfire handling to avoid
overlapping runs or to get this exact "spaced after completion" behavior.
"""

import asyncio
import logging

from app.config import settings
from app.crawler.orchestrator import run_crawl_cycle

logger = logging.getLogger(__name__)


async def crawl_loop() -> None:
    if settings.crawl_on_startup:
        await _run_cycle_safely()
    while True:
        await asyncio.sleep(settings.crawl_interval_seconds)
        await _run_cycle_safely()


async def _run_cycle_safely() -> None:
    try:
        await run_crawl_cycle()
    except Exception:  # noqa: BLE001 - the loop must survive a cycle failing outright
        logger.exception("Unhandled error in crawl cycle")
