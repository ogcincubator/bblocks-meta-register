import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import admin, bblocks, orgs, registers
from app.db.migrate import run_migrations_to_head
from app.mcp.server import mcp
from app.scheduler import crawl_loop

logging.basicConfig(level=logging.INFO)

# streamable_http_app() must be called before mcp.session_manager is accessible (it lazily
# creates the session manager on first call) -- see app/mcp/server.py's module docstring for
# why the MCP server is mounted here rather than run as its own process.
mcp_app = mcp.streamable_http_app()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    await asyncio.to_thread(run_migrations_to_head)
    task = asyncio.create_task(crawl_loop())
    # Starlette's Mount only forwards "http"/"websocket" ASGI scopes to a sub-app, never
    # "lifespan" (see Mount.matches), so the MCP session manager's lifespan has to be entered
    # here manually rather than relying on mounting alone to start it.
    async with mcp.session_manager.run():
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
app.mount("/mcp", mcp_app)
