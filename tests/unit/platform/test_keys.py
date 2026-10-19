"""Spec 12 T-PT-17: key values, the bastion key URL and its cache."""

from __future__ import annotations

import base64

import pytest
from pydantic import ValidationError
from tokens import BASTION, FRONTEND, KeyPair

from inkthread.core.config import Settings
from inkthread.platform.keys import KeyResolver, parse_public_key


def test_a_key_value_parses_with_a_bom_and_whitespace() -> None:
    key = parse_public_key("﻿ " + BASTION.spki_b64 + "\r\n")
    assert key.public_bytes_raw() == BASTION.public.public_bytes_raw()


@pytest.mark.parametrize(
    "value",
    [
        "not base64!",
        base64.b64encode(b"short").decode(),
        # An RSA-sized blob is valid base64 but no Ed25519 SPKI.
        base64.b64encode(b"\x30" * 300).decode(),
    ],
)
def test_a_bad_key_value_is_refused(value: str) -> None:
    with pytest.raises(ValueError, match="Ed25519"):
        parse_public_key(value)


def _settings(**kw: object) -> Settings:
    return Settings(_env_file=None, database_url="postgresql://x/y", llm_mode="off", **kw)


@pytest.mark.parametrize(
    "name", ["bastion_signing_key_public", "inkthread_frontend_signing_key_public"]
)
def test_settings_refuse_a_bad_key(name: str) -> None:
    with pytest.raises(ValidationError, match=name.upper()):
        _settings(**{name: "garbage"})
    assert _settings(**{name: KeyPair().spki_b64})


def test_settings_default_to_no_demo_mode_and_no_keys() -> None:
    s = _settings()
    assert s.demo_mode is False
    assert s.bastion_signing_key_public is None
    assert s.inkthread_frontend_signing_key_public is None


async def test_env_keys_need_no_fetch() -> None:
    async def fetch(_url: str) -> str:
        raise AssertionError("no fetch with an env key")

    r = KeyResolver(
        bastion=BASTION.spki_b64, bastion_url="https://b.example/k", frontend=None, fetch=fetch
    )
    keys = await r.keys()
    assert keys.bastion is not None
    assert keys.frontend is None


async def test_the_url_key_is_fetched_once_an_hour() -> None:
    calls: list[str] = []
    now = [0.0]

    async def fetch(url: str) -> str:
        calls.append(url)
        return BASTION.spki_b64

    r = KeyResolver(
        bastion=None,
        bastion_url="https://b.example/k",
        frontend=FRONTEND.spki_b64,
        fetch=fetch,
        clock=lambda: now[0],
    )
    assert (await r.keys()).bastion is not None
    now[0] = 3599.0
    await r.keys()
    assert len(calls) == 1
    now[0] = 3601.0
    await r.keys()
    assert len(calls) == 2


async def test_a_failed_fetch_keeps_the_last_key_and_retries_later() -> None:
    now = [0.0]
    answers: list[str | Exception] = [BASTION.spki_b64, OSError("down"), OSError("down")]

    async def fetch(_url: str) -> str:
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    r = KeyResolver(
        bastion=None,
        bastion_url="https://b.example/k",
        frontend=None,
        fetch=fetch,
        clock=lambda: now[0],
    )
    assert (await r.keys()).bastion is not None
    now[0] = 4000.0
    assert (await r.keys()).bastion is not None  # the last good key, not none
    now[0] = 4010.0
    await r.keys()
    assert len(answers) == 1  # a failure is not retried at once


async def test_a_failed_first_fetch_means_no_bastion_key() -> None:
    async def fetch(_url: str) -> str:
        raise OSError("down")

    r = KeyResolver(bastion=None, bastion_url="https://b.example/k", frontend=None, fetch=fetch)
    assert not (await r.keys()).any
