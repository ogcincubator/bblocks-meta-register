import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import admin, bblocks, orgs, registers
from app.db.migrate import run_migrations_to_head
from app.scheduler import crawl_loop

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    await asyncio.to_thread(run_migrations_to_head)
    task = asyncio.create_task(crawl_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="OGC Building Blocks Meta-Registry Viewer API", lifespan=lifespan)

app.include_router(orgs.router)
app.include_router(registers.router)
app.include_router(bblocks.router)
app.include_router(admin.router)
