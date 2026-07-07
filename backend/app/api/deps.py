import secrets
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.base import get_session
from app.search.embeddings import EmbeddingProvider, get_embedding_provider


async def db_session() -> AsyncIterator[AsyncSession]:
    async for session in get_session():
        yield session


SessionDep = Annotated[AsyncSession, Depends(db_session)]

# A plain function dependency (not a generator) -- tests override it the same way as
# db_session, via app.dependency_overrides, to swap in a fixed-vector fake and avoid needing a
# real Ollama instance reachable in CI/offline runs.
EmbeddingProviderDep = Annotated[EmbeddingProvider, Depends(get_embedding_provider)]


async def require_admin_key(x_admin_api_key: str | None = Header(default=None)) -> None:
    """Guards /admin/*. A no-op if BBLOCKS_ADMIN_API_KEY isn't configured (fine for local
    dev), so this must be set before the backend is reachable from anywhere untrusted."""
    if settings.admin_api_key is None:
        return
    if x_admin_api_key is None or not secrets.compare_digest(x_admin_api_key, settings.admin_api_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing admin API key")
