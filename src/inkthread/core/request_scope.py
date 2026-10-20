"""Run work under a request id, as slowquery-detective attributes statements (spec 13 § 2).

The job runner is a background task, outside any request's context, so a job's statements would be
charged to nobody. `attributed_to` sets the library's request-id context variable for a block of
work. slowquery-detective 0.2 reads that variable (`current_request_id`) but exposes no setter, so
this module is the one place that touches it; `tests/unit/test_request_scope.py` pins the behaviour.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from slowquery_detective import current_request_id
from slowquery_detective.tagging import _REQUEST_ID, parse_request_id


def tagged_request_id() -> str | None:
    """The `X-Request-Id` the library accepted for the current request, if any."""
    return current_request_id()


@contextmanager
def attributed_to(request_id: str | None) -> Iterator[None]:
    """Attribute the statements run inside the block to `request_id` (nobody when malformed)."""
    token = _REQUEST_ID.set(parse_request_id(request_id))
    try:
        yield
    finally:
        _REQUEST_ID.reset(token)
