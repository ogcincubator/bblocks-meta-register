import asyncio

import httpx
import pytest
import respx

from app.search.embeddings import OllamaEmbeddingProvider, PriorityGate

pytestmark = pytest.mark.asyncio


# --- PriorityGate ------------------------------------------------------------------------


async def test_high_priority_jumps_ahead_of_queued_low_priority():
    """A high-priority waiter queued *after* some low-priority ones is still served first,
    as long as it doesn't have to wait past the starvation guard."""
    gate = PriorityGate(starvation_guard_seconds=100)  # effectively disabled for this test
    order: list[str] = []
    release_holder = asyncio.Event()

    async def holder():
        async with gate.acquire_context(high=False):
            order.append("holder")
            await release_holder.wait()

    async def low(label: str):
        async with gate.acquire_context(high=False):
            order.append(label)

    async def high():
        async with gate.acquire_context(high=True):
            order.append("high")

    holder_task = asyncio.create_task(holder())
    await asyncio.sleep(0.05)  # holder has the gate

    low1_task = asyncio.create_task(low("low1"))
    await asyncio.sleep(0.01)
    low2_task = asyncio.create_task(low("low2"))
    await asyncio.sleep(0.01)
    high_task = asyncio.create_task(high())
    await asyncio.sleep(0.05)  # all three are now queued, waiting on the holder

    release_holder.set()
    await asyncio.gather(holder_task, low1_task, low2_task, high_task)

    assert order[:2] == ["holder", "high"]
    assert set(order[2:]) == {"low1", "low2"}


async def test_starvation_guard_lets_low_priority_through():
    """Sustained high-priority traffic doesn't starve a low-priority waiter forever -- it's
    let through once it has waited past the starvation guard."""
    guard_seconds = 0.15
    gate = PriorityGate(starvation_guard_seconds=guard_seconds)
    loop = asyncio.get_running_loop()
    low_queued_at: float | None = None
    low_acquired_at: float | None = None
    stop_spamming = asyncio.Event()

    async def low():
        nonlocal low_queued_at, low_acquired_at
        low_queued_at = loop.time()
        async with gate.acquire_context(high=False):
            low_acquired_at = loop.time()

    async def high_spammer():
        # Keeps re-queuing high-priority work fast enough that, without the starvation guard,
        # `_high_waiting` would rarely if ever hit zero.
        while not stop_spamming.is_set():
            async with gate.acquire_context(high=True):
                pass
            await asyncio.sleep(0.01)

    spammer_task = asyncio.create_task(high_spammer())
    await asyncio.sleep(0.02)  # let the spammer get going and hold/reacquire the gate

    low_task = asyncio.create_task(low())
    await low_task

    stop_spamming.set()
    await spammer_task

    assert low_queued_at is not None
    assert low_acquired_at is not None
    # Generous tolerance over the guard window itself for scheduling jitter -- the point is
    # that it's bounded, not that it fires the instant the guard elapses.
    assert low_acquired_at - low_queued_at <= guard_seconds + 0.3


# --- OllamaEmbeddingProvider wiring -------------------------------------------------------


@respx.mock
async def test_embed_query_is_high_priority_embed_documents_is_low(monkeypatch):
    seen_priorities: list[bool] = []
    original_acquire_context = PriorityGate.acquire_context

    def spying_acquire_context(self, *, high):
        seen_priorities.append(high)
        return original_acquire_context(self, high=high)

    monkeypatch.setattr(PriorityGate, "acquire_context", spying_acquire_context)

    respx.post("http://ollama.test/api/embed").mock(
        return_value=httpx.Response(200, json={"embeddings": [[0.1, 0.2]]})
    )
    provider = OllamaEmbeddingProvider(base_url="http://ollama.test")

    await provider.embed_query("hello")
    await provider.embed_documents(["doc"])

    assert seen_priorities == [True, False]
