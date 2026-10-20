"""Spec 13 T-SQ-4: running work under a request id, as slowquery-detective sees it."""

from __future__ import annotations

import asyncio

from slowquery_detective import current_request_id

from inkthread.core.request_scope import attributed_to, tagged_request_id


def test_T_SQ_4_inside_the_scope_the_library_sees_the_id() -> None:
    assert current_request_id() is None
    with attributed_to("R-1"):
        assert current_request_id() == "R-1"
        assert tagged_request_id() == "R-1"
        with attributed_to("R-2"):
            assert current_request_id() == "R-2"
        assert current_request_id() == "R-1"
    assert current_request_id() is None


def test_T_SQ_4_a_malformed_or_missing_id_attributes_to_nobody() -> None:
    for bad in (None, "", "-x", "a b", "x" * 129, "café"):
        with attributed_to(bad):
            assert current_request_id() is None


async def test_T_SQ_4_tasks_started_inside_inherit_the_id() -> None:
    async def read() -> str | None:
        return current_request_id()

    with attributed_to("R-3"):
        task = asyncio.create_task(read())
    assert await task == "R-3"
    assert await asyncio.to_thread(current_request_id) is None
