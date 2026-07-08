import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import admin, bblocks, orgs, registers
from app.db.migrate import run_migrations_to_head
from app.mcp.server import mcp
from app.scheduler import crawl_loop

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# streamable_http_app() must be called before mcp.session_manager is accessible (it lazily
# creates the session manager on first call) -- see app/mcp/server.py's module docstring for
# why the MCP server is mounted here rather than run as its own process.
mcp_app = mcp.streamable_http_app()


def _reenable_app_loggers() -> None:
    """Two separate things disable our `app.*` module-level loggers on every startup, both via
    `logging.config.fileConfig`/`dictConfig`'s default `disable_existing_loggers=True` (which
    disables every already-instantiated logger not in the config being applied):

    1. `fastapi dev`/uvicorn imports this module (instantiating all `app.*` loggers) before
       uvicorn builds its Config and runs configure_logging().
    2. `run_migrations_to_head()` -> Alembic's env.py calls `fileConfig(alembic.ini)`, which
       runs *after* this function's first call in lifespan() below and disables them again.

    Hence this must run again after migrations, not just once before them."""
    for name, logger_obj in logging.root.manager.loggerDict.items():
        if name.startswith("app") and isinstance(logger_obj, logging.Logger):
            logger_obj.disabled = False


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    _reenable_app_loggers()
    await asyncio.to_thread(run_migrations_to_head)
    _reenable_app_loggers()
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

# Public API is read-only and unauthenticated by design (see docs/02-viewer-application.md), so
# allowing any origin doesn't widen the actual attack surface -- it just lets the frontend call
# this API directly from any host it's served from, without a proxy.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(orgs.router)
app.include_router(registers.router)
app.include_router(bblocks.router)
app.include_router(admin.router)
app.mount("/mcp", mcp_app)


@app.exception_handler(Exception)
async def log_unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    """Uvicorn's default ASGI-level logging of unhandled exceptions is easy to miss/suppress
    (e.g. behind reload-subprocess output) -- log explicitly at the FastAPI layer so a 500
    always leaves a traceback in this app's own logger, not just uvicorn's."""
    logger.exception("Unhandled exception for %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})
