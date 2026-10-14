"""The request budget (spec 05 § 6): per job, per UTC day, and the account's own free quota."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime

import httpx
import structlog
from pydantic import BaseModel, ValidationError

_log = structlog.get_logger(__name__)


def utc_day(at: datetime) -> date:
    """The UTC calendar day of an aware timestamp; the daily cap resets at 00:00 UTC."""
    if at.tzinfo is None:
        msg = "utc_day needs an aware datetime"
        raise ValueError(msg)
    return at.astimezone(UTC).date()


class Budget:
    """One job's budget. Every HTTP attempt takes one request; recorded hits take none.

    - `per_document` attempts per job, counted here;
    - `daily_cap` attempts per UTC day across jobs, from `daily_count` (rows in `llm_calls`), asked
      on every acquire;
    - before the first attempt, `account_remaining` (OpenRouter's `/key`): at or below `reserve`,
      the job's budget is spent. A failed check (an exception or None) leaves the local counts to
      decide.
    """

    def __init__(
        self,
        *,
        per_document: int,
        daily_cap: int,
        reserve: int,
        daily_count: Callable[[], Awaitable[int]],
        account_remaining: Callable[[], Awaitable[int | None]],
    ) -> None:
        if min(per_document, daily_cap, reserve) < 0:
            msg = "budget limits must be non-negative"
            raise ValueError(msg)
        self._per_document = per_document
        self._daily_cap = daily_cap
        self._reserve = reserve
        self._daily_count = daily_count
        self._account_remaining = account_remaining
        self._spent = 0
        self._checked = False
        self._exhausted = False

    async def acquire(self) -> bool:
        """Take one request, or refuse."""
        if not self._checked:
            self._checked = True
            await self._check_account()
        if self._exhausted or self._spent >= self._per_document:
            return False
        if await self._daily_count() >= self._daily_cap:
            return False
        self._spent += 1
        return True

    def spent(self) -> int:
        """Requests taken by this job."""
        return self._spent

    async def _check_account(self) -> None:
        try:
            remaining = await self._account_remaining()
        except Exception as exc:  # noqa: BLE001 - any failure falls back to the local counts
            _log.warning("account_check_failed", error=type(exc).__name__)
            return
        if remaining is not None and remaining <= self._reserve:
            _log.info("account_reserve_reached", remaining=remaining, reserve=self._reserve)
            self._exhausted = True


class _FreeRequests(BaseModel):
    remaining: int


class _KeyData(BaseModel):
    free_model_daily_requests: _FreeRequests


class _KeyInfo(BaseModel):
    data: _KeyData


async def account_remaining_from_openrouter(
    http: httpx.AsyncClient, base_url: str, api_key: str, *, timeout_s: float = 10.0
) -> int | None:
    """`data.free_model_daily_requests.remaining` from `GET {base}/key`, or None on any failure."""
    try:
        response = await http.get(
            base_url.rstrip("/") + "/key",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout_s,
        )
        response.raise_for_status()
        info = _KeyInfo.model_validate_json(response.content)
    except (httpx.HTTPError, ValidationError) as exc:
        _log.warning("account_key_check_failed", error=type(exc).__name__)
        return None
    return info.data.free_model_daily_requests.remaining
