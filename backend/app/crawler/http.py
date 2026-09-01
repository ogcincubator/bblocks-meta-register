import asyncio
import logging
import random
import time
from urllib.parse import urlsplit

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class PerHostThrottle:
    """Enforces at most one in-flight request per host, with a minimum interval between
    requests, and backs off on 429/5xx responses -- regardless of which register-level worker
    issues the request (the register-level worker pool alone can't prevent two different
    registers on the same host from being hit concurrently). The per-host lock is held for the
    whole request (see get_json), not just the interval wait, so a slow response from one
    register can't overlap with another request to the same host -- GitHub read timeouts have
    been observed under concurrent load, and a request that's merely spaced out but still
    overlapping in flight wouldn't avoid that.

    Each scheduled interval gets `random.uniform(0, jitter_seconds)` added on top of
    `min_interval_seconds`, so requests to a host land at an irregular cadence rather than a
    perfectly even one-per-N-seconds beat."""

    def __init__(self, min_interval_seconds: float, jitter_seconds: float = 0.0):
        self._min_interval = min_interval_seconds
        self._jitter = jitter_seconds
        self._locks: dict[str, asyncio.Lock] = {}
        self._next_allowed_at: dict[str, float] = {}

    def lock_for(self, host: str) -> asyncio.Lock:
        if host not in self._locks:
            self._locks[host] = asyncio.Lock()
        return self._locks[host]

    async def wait(self, host: str) -> None:
        now = time.monotonic()
        next_allowed = self._next_allowed_at.get(host, 0.0)
        if now < next_allowed:
            await asyncio.sleep(next_allowed - now)
        interval = self._min_interval + random.uniform(0, self._jitter)
        self._next_allowed_at[host] = time.monotonic() + interval

    def back_off(self, host: str, delay_seconds: float) -> None:
        self._next_allowed_at[host] = time.monotonic() + delay_seconds


_throttle = PerHostThrottle(settings.crawl_per_host_min_interval_seconds, settings.crawl_per_host_jitter_seconds)


async def _get_with_retry(client: httpx.AsyncClient, url: str) -> httpx.Response:
    """Shared throttled-GET-with-retry core for get_json/get_text -- honors per-host throttling
    and retries with exponential backoff on 429/5xx (a host signaling it's overloaded should be
    backed off, not hammered). Holds the per-host lock for the whole call so at most one request
    per host is ever in flight, even across concurrent register-crawl workers."""
    host = urlsplit(url).netloc
    last_exc: Exception | None = None
    async with _throttle.lock_for(host):
        for attempt in range(settings.http_max_retries):
            await _throttle.wait(host)
            try:
                response = await client.get(url, timeout=settings.http_timeout_seconds)
            except httpx.HTTPError as exc:
                last_exc = exc
                backoff = 2**attempt
                logger.warning("Request error for %s (attempt %d): %s", url, attempt + 1, exc)
                _throttle.back_off(host, backoff)
                await asyncio.sleep(backoff)
                continue

            if response.status_code == 429 or response.status_code >= 500:
                backoff = 2**attempt
                logger.warning(
                    "Got %d from %s (attempt %d), backing off %ds", response.status_code, url, attempt + 1, backoff
                )
                _throttle.back_off(host, backoff)
                await asyncio.sleep(backoff)
                continue

            response.raise_for_status()
            return response

    logger.error("Giving up on %s after %d attempts", url, settings.http_max_retries)
    raise last_exc or httpx.HTTPStatusError(
        f"Exhausted retries fetching {url}", request=None, response=None  # type: ignore[arg-type]
    )


async def get_json(client: httpx.AsyncClient, url: str) -> dict | list:
    """GET a URL and parse JSON. See _get_with_retry for throttling/retry behavior."""
    response = await _get_with_retry(client, url)
    return response.json()


async def get_text(client: httpx.AsyncClient, url: str) -> tuple[str, str | None]:
    """GET a URL, returning (body text, Content-Type header) rather than parsing JSON -- used for
    non-JSON documents like an `ontology` file (Turtle or RDF/XML; see
    app/search/chunking.py's `_ontology_bindings()`). The Content-Type is returned alongside the
    body since it's one of the signals used to pick an rdflib parser format when the URL's file
    extension alone doesn't say (e.g. no extension, or an extension-less redirect target). See
    _get_with_retry for throttling/retry behavior."""
    response = await _get_with_retry(client, url)
    return response.text, response.headers.get("content-type")


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(follow_redirects=True)
