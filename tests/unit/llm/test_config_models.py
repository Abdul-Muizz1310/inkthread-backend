"""Spec 05 § 6 / spec 10: the verifier's model must differ from the producer's (T-AG-25)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from inkthread.core.config import Settings


def test_primary_equal_to_fast_fails_at_startup() -> None:  # T-AG-25
    with pytest.raises(ValidationError, match="must differ"):
        Settings(
            database_url="postgresql://x",
            llm_mode="off",
            openrouter_model_primary="same/model:free",
            openrouter_model_fast="same/model:free",
        )
