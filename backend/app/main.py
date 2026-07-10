import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from app.api import admin, bblocks, orgs, registers
from app.db.migrate import run_migrations_to_head
from app.logging_config import configure_logging
from app.mcp.server import mcp
from app.scheduler import crawl_loop

configure_logging()
logger = logging.getLogger(__name__)

# streamable_http_app() must be called before mcp.session_manager is accessible (it lazily
# creates the session manager on first call) -- see app/mcp/server.py's module docstring for
# why the MCP server is mounted here rather than run as its own process.
mcp_app = mcp.streamable_http_app()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    await asyncio.to_thread(run_migrations_to_head)
    configure_logging()  # undo Alembic's fileConfig() re-disabling app.* loggers, see module docstring
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


# There's no ratified ".well-known" schema for MCP server discovery yet, so this mirrors the
# `mcpServers` map shape that `claude mcp add`/Claude Desktop configs and most existing MCP
# directory crawlers already expect, keyed by server name, rather than inventing a new one.
@app.get("/.well-known/mcp.json", include_in_schema=False)
async def mcp_manifest(request: Request) -> JSONResponse:
    mcp_url = str(request.base_url).rstrip("/") + "/mcp"
    return JSONResponse(
        {
            "mcpServers": {
                mcp.name: {
                    "url": mcp_url,
                    "transport": "streamable-http",
                    "description": mcp.instructions,
                }
            }
        }
    )


# FastAPI/OpenAPI has no built-in field for "here's an MCP server alongside this REST API" --
# `x-mcp` is a non-standard vendor extension (OpenAPI reserves the `x-` prefix for exactly this),
# picked up by tooling that knows to look for it but harmless to everyone else.
def _custom_openapi() -> dict:
    if app.openapi_schema is None:
        app.openapi_schema = get_openapi(
            title=app.title,
            version=app.version,
            routes=app.routes,
        )
        app.openapi_schema["info"]["x-mcp"] = {
            "url": "/mcp",
            "wellKnown": "/.well-known/mcp.json",
            "transport": "streamable-http",
            "description": mcp.instructions,
        }
    return app.openapi_schema


app.openapi = _custom_openapi


@app.exception_handler(Exception)
async def log_unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    """Uvicorn's default ASGI-level logging of unhandled exceptions is easy to miss/suppress
    (e.g. behind reload-subprocess output) -- log explicitly at the FastAPI layer so a 500
    always leaves a traceback in this app's own logger, not just uvicorn's."""
    logger.exception("Unhandled exception for %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})
