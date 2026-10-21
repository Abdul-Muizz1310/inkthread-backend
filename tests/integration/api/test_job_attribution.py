"""Spec 13 T-SQ-4: a job's stored request id never fails the job."""

from __future__ import annotations

import uuid
from collections.abc import Callable

import pdfs
import pytest
from apiharness import ApiFactory
from structlog.testing import capture_logs

from inkthread.core.config import Settings
from inkthread.models import Job

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("stored", ["not a valid id!", "", None])
async def test_T_SQ_4_a_bad_or_missing_stored_id_runs_the_job_unattributed(
    api: ApiFactory, make_settings: Callable[..., Settings], stored: str | None
) -> None:
    async with api(settings=make_settings(llm_mode="replay")) as a:  # runner not started
        up = (await a.upload(pdfs.sectioned())).json()
        services = a.app.state.services
        async with services.sessions() as s, s.begin():
            job = await s.get(Job, uuid.UUID(up["job"]["id"]))
            assert job is not None
            job.request_id = stored
        with capture_logs() as logs:
            assert await services.runner.run_once()
        body = (await a.client.get(f"/jobs/{up['job']['id']}")).json()
    assert body["status"] == "succeeded"
    warned = [e for e in logs if e["event"] == "job_request_id_refused"]
    if stored is None:
        assert warned == []
    else:
        assert len(warned) == 1
        assert warned[0]["log_level"] == "warning"
