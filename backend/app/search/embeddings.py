"""EmbeddingProvider interface (docs/03-indexing-and-search.md) with two implementations,
selected via `settings.embedding_provider`. Ollama is the priority implementation (self-hosted,
no external dependency); the OpenAI-compatible one covers deployments that would rather call a
hosted `/embeddings` endpoint than run a model server.

Query-side instruction prefixing is a provider-level concern per doc 03 -- nomic-embed-text-v2
family models expect inputs prefixed with a task instruction ("search_document: " for indexed
content, "search_query: " for queries), so that prefixing lives here, not in the chunking or
search-service code that calls this interface.
"""

import asyncio
import logging
from typing import Protocol

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class EmbeddingProvider(Protocol):
    async def embed_documents(self, texts: list[str], labels: list[str] | None = None) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


# Ollama serves one embedding request at a time on typical (single-GPU/CPU) deployments; the
# crawl's register-level worker pool (crawl_worker_pool_size) otherwise lets several registers'
# embed_documents calls race each other for it concurrently, queueing behind Ollama's internal
# request handling until they blow past http_timeout_seconds. This lock is module-level (not
# per-instance) since get_embedding_provider() hands out a fresh instance per call -- it
# serializes only the embedding request itself, not the surrounding HTTP fetches/chunking, which
# stay parallel across registers.
_ollama_request_lock = asyncio.Lock()


class OllamaEmbeddingProvider:
    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        batch_size: int | None = None,
    ):
        self._base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self._model = model or settings.ollama_embedding_model
        self._batch_size = batch_size or settings.embedding_batch_size

    async def _embed(self, prefixed_texts: list[str], labels: list[str] | None = None) -> list[list[float]]:
        if not prefixed_texts:
            return []
        embeddings: list[list[float]] = []
        async with httpx.AsyncClient(timeout=settings.embedding_http_timeout_seconds) as client:
            for start in range(0, len(prefixed_texts), self._batch_size):
                batch = prefixed_texts[start : start + self._batch_size]
                batch_labels = labels[start : start + self._batch_size] if labels else None
                async with _ollama_request_lock:
                    try:
                        response = await client.post(
                            f"{self._base_url}/api/embed",
                            json={"model": self._model, "input": batch},
                        )
                        response.raise_for_status()
                    except httpx.HTTPError:
                        # labels (e.g. "<bblock_id>:<chunk_key>") identify what was in flight so
                        # a timeout/error can be traced back to the specific content that
                        # triggered it, not just "embedding failed somewhere in this register".
                        logger.error(
                            "Embedding request failed for batch %s",
                            batch_labels if batch_labels else f"[{start}:{start + len(batch)}]",
                        )
                        raise
                    embeddings.extend(response.json()["embeddings"])
        return embeddings

    async def embed_documents(self, texts: list[str], labels: list[str] | None = None) -> list[list[float]]:
        return await self._embed([f"search_document: {text}" for text in texts], labels)

    async def embed_query(self, text: str) -> list[float]:
        return (await self._embed([f"search_query: {text}"]))[0]


class OpenAICompatibleEmbeddingProvider:
    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ):
        base = base_url or settings.openai_compatible_base_url
        if not base:
            raise ValueError("openai_compatible_base_url must be set to use this provider")
        self._base_url = base.rstrip("/")
        self._model = model or settings.openai_compatible_embedding_model
        self._api_key = api_key or settings.openai_compatible_api_key

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        async with httpx.AsyncClient(timeout=settings.embedding_http_timeout_seconds) as client:
            response = await client.post(
                f"{self._base_url}/embeddings",
                json={"model": self._model, "input": texts},
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()["data"]
        return [item["embedding"] for item in data]

    async def embed_documents(self, texts: list[str], labels: list[str] | None = None) -> list[list[float]]:
        return await self._embed(texts)

    async def embed_query(self, text: str) -> list[float]:
        return (await self._embed([text]))[0]


def get_embedding_provider() -> EmbeddingProvider:
    if settings.embedding_provider == "openai_compatible":
        return OpenAICompatibleEmbeddingProvider()
    return OllamaEmbeddingProvider()
