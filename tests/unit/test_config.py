"""Spec 10 § 1 and § 5: settings validate at boot (T-OPS-2) and resolve the commit SHA (T-OPS-6)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from inkthread.core.config import BlobStoreKind, LlmMode, Settings

BASE = {"database_url": "postgresql://u:p@localhost:5432/db", "llm_mode": "off"}


def make(**overrides: object) -> Settings:
    return Settings(_env_file=None, **{**BASE, **overrides})


def test_defaults_match_the_spec() -> None:
    s = make()
    assert s.app_env == "development"
    assert s.cors_origins == ["http://localhost:3000"]
    assert s.blob_store is BlobStoreKind.LOCAL
    assert s.openrouter_model_primary == "nvidia/nemotron-3-super-120b-a12b:free"
    assert s.openrouter_model_fast == "google/gemma-4-31b-it:free"
    assert s.openrouter_model_fallback == "google/gemma-4-26b-a4b-it:free"
    assert s.llm_max_requests_per_document == 8
    assert s.llm_daily_request_cap == 40
    assert s.llm_account_reserve == 10
    assert s.llm_max_tokens == 12000
    assert s.max_upload_bytes == 15 * 1024 * 1024
    assert s.max_pages == 40
    assert s.max_queue == 10
    assert s.uploads_per_hour == 5
    assert s.retention_days == 7
    assert s.r2_prefix == "inkthread/"


def test_cors_origins_parse_a_comma_list() -> None:
    s = make(cors_origins="https://a.example, https://b.example")
    assert s.cors_origins == ["https://a.example", "https://b.example"]


def test_refuses_primary_equal_to_fast() -> None:
    with pytest.raises(ValidationError, match="must differ"):
        make(openrouter_model_primary="x/y:free", openrouter_model_fast="x/y:free")


def test_refuses_an_unknown_llm_mode() -> None:
    with pytest.raises(ValidationError):
        make(llm_mode="sometimes")


def test_refuses_wildcard_cors_in_production() -> None:
    with pytest.raises(ValidationError, match="CORS"):
        make(app_env="production", cors_origins="*")


def test_allows_wildcard_cors_in_development() -> None:
    assert make(cors_origins="*").cors_origins == ["*"]


def test_refuses_r2_without_credentials() -> None:
    with pytest.raises(ValidationError, match="R2"):
        make(blob_store="r2")


def test_accepts_r2_with_credentials() -> None:
    s = make(
        blob_store="r2",
        r2_account_id="acc",
        r2_access_key_id="key",
        r2_secret_access_key="secret",
        r2_bucket="bucket",
        r2_endpoint="https://acc.r2.cloudflarestorage.com",
    )
    assert s.blob_store is BlobStoreKind.R2


def test_refuses_live_llm_without_a_key() -> None:
    with pytest.raises(ValidationError, match="OPENROUTER_API_KEY"):
        make(llm_mode="live", openrouter_api_key=None)


def test_live_llm_with_a_key_is_accepted() -> None:
    assert make(llm_mode="live", openrouter_api_key="sk-test").llm_mode is LlmMode.LIVE


def test_secrets_are_not_in_the_repr() -> None:
    s = make(llm_mode="live", openrouter_api_key="sk-very-secret", admin_token="tok-secret")
    assert "sk-very-secret" not in repr(s)
    assert "tok-secret" not in repr(s)


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"COMMIT_SHA": "abc1234", "RENDER_GIT_COMMIT": "def", "GITHUB_SHA": "ghi"}, "abc1234"),
        ({"RENDER_GIT_COMMIT": "def5678", "GITHUB_SHA": "ghi"}, "def5678"),
        ({"GITHUB_SHA": "9abcdef"}, "9abcdef"),
        ({}, "unknown"),
        ({"COMMIT_SHA": "", "RENDER_GIT_COMMIT": "unknown", "GITHUB_SHA": "1234567"}, "1234567"),
    ],
)
def test_commit_sha_falls_back(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], expected: str
) -> None:
    for name in ("COMMIT_SHA", "RENDER_GIT_COMMIT", "GITHUB_SHA"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert make().commit_sha == expected
