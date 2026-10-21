"""Platform tokens for tests: Ed25519 key pairs and a minter for any claims (spec 12)."""

from __future__ import annotations

import base64
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


@dataclass(frozen=True)
class KeyPair:
    private: Ed25519PrivateKey = field(default_factory=Ed25519PrivateKey.generate)

    @property
    def public(self) -> Ed25519PublicKey:
        return self.private.public_key()

    @property
    def spki_b64(self) -> str:
        """The public half as the env var holds it: base64 SPKI DER."""
        der = self.public.public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        return base64.b64encode(der).decode()


BASTION = KeyPair()
FRONTEND = KeyPair()
OTHER = KeyPair()


def claims(**overrides: Any) -> dict[str, Any]:
    """A bastion token's claims for inkthread, minted now, with `overrides` (None drops a claim)."""
    now = int(time.time())
    base: dict[str, Any] = {
        "iss": "bastion",
        "aud": "inkthread",
        "service": "inkthread",
        "sub": "v_abcdefghij",
        "role": "viewer",
        "iat": now,
        "exp": now + 60,
        "jti": str(uuid.uuid4()),
    }
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


def frontend_claims(**overrides: Any) -> dict[str, Any]:
    """The claims inkthread-frontend mints (DR-0030)."""
    return claims(
        **{
            "iss": "inkthread-frontend",
            "sub": "inkthread-frontend",
            "role": "frontend",
            **overrides,
        }
    )


def mint(payload: dict[str, Any], key: KeyPair = BASTION) -> str:
    return jwt.encode(payload, key.private, algorithm="EdDSA", headers={"kid": "test"})


def bastion_token(**overrides: Any) -> str:
    return mint(claims(**overrides), BASTION)


def frontend_token(**overrides: Any) -> str:
    return mint(frontend_claims(**overrides), FRONTEND)
