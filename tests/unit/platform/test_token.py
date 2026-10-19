"""Spec 12 § 4: the pure verifier (conformance cases 1-9, and T-PT-15)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import pytest
from tokens import BASTION, FRONTEND, OTHER, bastion_token, claims, frontend_token, mint

from inkthread.platform.token import Principal, TokenRejected, TrustedKeys, verify

KEYS = TrustedKeys(bastion=BASTION.public, frontend=FRONTEND.public)


def check(token: str, *, keys: TrustedKeys = KEYS, now: float | None = None) -> Principal:
    return verify(token, keys, now=time.time() if now is None else now)


def refused(token: str, **kw: object) -> str:
    with pytest.raises(TokenRejected) as info:
        check(token, **kw)  # type: ignore[arg-type]
    return info.value.check


def test_T_PT_1_a_bastion_token_for_inkthread_is_accepted() -> None:
    p = check(bastion_token())
    assert p == Principal(iss="bastion", sub="v_abcdefghij", role="viewer")
    assert p.rate_key == "bastion:v_abcdefghij"


def test_T_PT_1_a_frontend_token_for_inkthread_is_accepted() -> None:
    p = check(frontend_token())
    assert p.iss == "inkthread-frontend"
    assert p.rate_key == "inkthread-frontend:inkthread-frontend"


@pytest.mark.parametrize("aud", ["inkprint", "paper-trail", "magpie", "slowquery", "", "INKTHREAD"])
def test_T_PT_2_another_services_audience_is_refused(aud: str) -> None:
    assert refused(bastion_token(aud=aud)) == "aud"
    assert refused(frontend_token(aud=aud)) == "aud"


def test_T_PT_3_a_missing_or_list_audience_is_refused() -> None:
    assert refused(mint(claims(aud=None))) == "aud"
    assert refused(bastion_token(aud=["inkthread"])) == "aud"
    assert refused(bastion_token(aud=["inkthread", "inkprint"])) == "aud"


def test_T_PT_4_the_key_decides_the_issuer() -> None:
    forged = mint(claims(iss="bastion"), FRONTEND)
    assert refused(forged) == "iss"
    reverse = mint(claims(iss="inkthread-frontend", role="frontend"), BASTION)
    assert refused(reverse) == "iss"


@pytest.mark.parametrize("role", ["viewer", "admin", "", None])
def test_T_PT_5_a_frontend_token_needs_the_frontend_role(role: str | None) -> None:
    assert refused(frontend_token(role=role)) == "role"


def test_T_PT_6_expiry_has_ten_seconds_of_leeway() -> None:
    now = int(time.time())
    assert check(bastion_token(iat=now - 65, exp=now - 5), now=now)
    assert refused(bastion_token(iat=now - 75, exp=now - 15), now=now) == "exp"


def test_T_PT_7_issued_at_has_ten_seconds_of_leeway() -> None:
    now = int(time.time())
    assert check(bastion_token(iat=now + 5, exp=now + 65), now=now)
    assert refused(bastion_token(iat=now + 15, exp=now + 75), now=now) == "iat"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def test_T_PT_8_none_and_hs256_are_refused() -> None:
    body = _b64(json.dumps(claims()).encode())
    unsigned = f"{_b64(json.dumps({'alg': 'none', 'typ': 'JWT'}).encode())}.{body}."
    assert refused(unsigned) == "alg"
    head = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    secret = BASTION.spki_b64.encode()  # the classic confusion: the public key as an HMAC secret
    sig = hmac.new(secret, f"{head}.{body}".encode(), hashlib.sha256).digest()
    assert refused(f"{head}.{body}.{_b64(sig)}") == "alg"


def test_T_PT_9_a_tampered_payload_is_refused() -> None:
    head, _, sig = bastion_token().split(".")
    body = _b64(json.dumps(claims(sub="v_someoneels")).encode())
    assert refused(f"{head}.{body}.{sig}") == "signature"


def test_T_PT_9_an_unknown_key_is_refused() -> None:
    assert refused(mint(claims(), OTHER)) == "signature"


@pytest.mark.parametrize(
    ("overrides", "now", "failed"),
    [
        ({"iat": 1_000, "exp": 1_301}, 1_100, "lifetime"),
        ({"iat": 2_000, "exp": 2_000}, 2_000, "lifetime"),
        ({"exp": "9999999999"}, None, "exp"),
        ({"exp": True}, None, "exp"),
        ({"exp": None}, None, "exp"),
        ({"iat": None}, None, "iat"),
        ({"iat": 1.5}, None, "iat"),
        ({"sub": ""}, None, "sub"),
        ({"sub": None}, None, "sub"),
        ({"sub": 7}, None, "sub"),
    ],
)
def test_T_PT_15_other_bad_claims_are_refused(
    overrides: dict[str, object], now: float | None, failed: str
) -> None:
    assert refused(mint(claims(**overrides)), now=now) == failed


@pytest.mark.parametrize("token", ["", "abc", "a.b", "a.b.c", "....", "x" * 5000])
def test_T_PT_15_malformed_tokens_are_refused(token: str) -> None:
    assert refused(token) in {"malformed", "alg"}


def test_only_the_configured_keys_count() -> None:
    no_frontend = TrustedKeys(bastion=BASTION.public, frontend=None)
    assert refused(frontend_token(), keys=no_frontend) == "signature"
    no_bastion = TrustedKeys(bastion=None, frontend=FRONTEND.public)
    assert refused(bastion_token(), keys=no_bastion) == "signature"
    assert not TrustedKeys(bastion=None, frontend=None).any
    assert KEYS.any


def test_the_same_key_for_both_issuers_still_matches_each() -> None:
    same = TrustedKeys(bastion=BASTION.public, frontend=BASTION.public)
    assert check(mint(claims(), BASTION), keys=same).iss == "bastion"
    assert check(mint(claims(iss="inkthread-frontend", role="frontend"), BASTION), keys=same)
