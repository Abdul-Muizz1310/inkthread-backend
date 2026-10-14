"""Spec 05 § 6 budget: per-document, daily cap, account reserve (T-AG-11..13)."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import respx
from fake_llm import MemoryCallLog

from inkthread.llm.budget import Budget, account_remaining_from_openrouter
from inkthread.llm.ports import LlmCall

BASE = "https://openrouter.test/api/v1"


async def zero() -> int:
    return 0


async def unknown() -> int | None:
    return None


def call() -> LlmCall:
    return LlmCall(
        task="classify",
        model="a/m",
        request_key="k" * 64,
        cached=False,
        status="ok",
        http_status=200,
        latency_ms=1,
        prompt_tokens=None,
        completion_tokens=None,
    )


async def test_ninth_attempt_in_a_job_is_refused() -> None:  # T-AG-11
    budget = Budget(
        per_document=8, daily_cap=40, reserve=10, daily_count=zero, account_remaining=unknown
    )
    granted = [await budget.acquire() for _ in range(9)]
    assert granted == [True] * 8 + [False]
    assert budget.spent() == 8


async def test_daily_cap_counts_across_jobs_and_resets_at_utc_midnight() -> None:  # T-AG-12
    log = MemoryCallLog(now=datetime(2026, 10, 14, 23, 59, tzinfo=UTC))

    def job() -> Budget:
        return Budget(
            per_document=8,
            daily_cap=3,
            reserve=10,
            daily_count=log.count_today,
            account_remaining=unknown,
        )

    first = job()
    for _ in range(2):
        assert await first.acquire()
        await log.record(call())
    second = job()
    assert await second.acquire()
    await log.record(call())
    assert not await second.acquire()
    log.now = datetime(2026, 10, 15, 0, 0, tzinfo=UTC)
    assert await job().acquire()


async def test_cached_rows_do_not_count_toward_the_daily_cap() -> None:  # T-AG-14
    log = MemoryCallLog()
    for _ in range(5):
        await log.record(
            LlmCall(
                task="classify",
                model="a/m",
                request_key="k" * 64,
                cached=True,
                status="hit",
                http_status=None,
                latency_ms=0,
                prompt_tokens=None,
                completion_tokens=None,
            )
        )
    budget = Budget(
        per_document=8,
        daily_cap=1,
        reserve=0,
        daily_count=log.count_today,
        account_remaining=unknown,
    )
    assert await budget.acquire()


async def test_account_at_reserve_spends_the_job_budget() -> None:  # T-AG-13
    checks = 0

    async def remaining() -> int | None:
        nonlocal checks
        checks += 1
        return 10

    budget = Budget(
        per_document=8, daily_cap=40, reserve=10, daily_count=zero, account_remaining=remaining
    )
    assert not await budget.acquire()
    assert not await budget.acquire()
    assert checks == 1
    assert budget.spent() == 0


async def test_account_above_reserve_and_failing_check_fall_back_to_local() -> None:  # T-AG-13
    async def plenty() -> int | None:
        return 11

    async def broken() -> int | None:
        raise RuntimeError("down")

    for check in (plenty, broken):
        budget = Budget(
            per_document=1, daily_cap=40, reserve=10, daily_count=zero, account_remaining=check
        )
        assert await budget.acquire()
        assert not await budget.acquire()


@respx.mock
async def test_account_remaining_reads_the_key_endpoint() -> None:
    route = respx.get(f"{BASE}/key").mock(
        return_value=httpx.Response(
            200, json={"data": {"label": "x", "free_model_daily_requests": {"remaining": 37}}}
        )
    )
    async with httpx.AsyncClient() as http:
        assert await account_remaining_from_openrouter(http, BASE, "sk-secret") == 37
    assert route.calls.last.request.headers["authorization"] == "Bearer sk-secret"


@respx.mock
async def test_account_remaining_is_none_on_failure_or_odd_shape() -> None:
    async with httpx.AsyncClient() as http:
        respx.get(f"{BASE}/key").mock(return_value=httpx.Response(500))
        assert await account_remaining_from_openrouter(http, BASE, "k") is None
        respx.get(f"{BASE}/key").mock(return_value=httpx.Response(200, json={"data": {}}))
        assert await account_remaining_from_openrouter(http, BASE, "k") is None
        respx.get(f"{BASE}/key").mock(side_effect=httpx.ConnectError("no"))
        assert await account_remaining_from_openrouter(http, BASE, "k") is None
