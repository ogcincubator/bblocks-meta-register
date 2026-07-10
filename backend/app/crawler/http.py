import asyncio
import logging
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
    overlapping in flight wouldn't avoid that."""

    def __init__(self, min_interval_seconds: float):
        self._min_interval = min_interval_seconds
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
        self._next_allowed_at[host] = time.monotonic() + self._min_interval

    def back_off(self, host: str, delay_seconds: float) -> None:
        self._next_allowed_at[host] = time.monotonic() + delay_seconds


_throttle = PerHostThrottle(settings.crawl_per_host_min_interval_seconds)


async def get_json(client: httpx.AsyncClient, url: str) -> dict | list:
    """GET a URL and parse JSON, honoring per-host throttling and retrying with exponential
    backoff on 429/5xx (a host signaling it's overloaded should be backed off, not hammered).
    Holds the per-host lock for the whole call so at most one request per host is ever in
    flight, even across concurrent register-crawl workers."""
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
            return response.json()

    raise last_exc or httpx.HTTPStatusError(
        f"Exhausted retries fetching {url}", request=None, response=None  # type: ignore[arg-type]
    )


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(follow_redirects=True)
