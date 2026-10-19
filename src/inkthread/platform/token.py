"""Platform token verification, contract v2 (spec 12 § 2). Pure: no I/O, no clock of its own.

`verify` takes the token, the trusted keys and the time, and returns who is calling or raises
`TokenRejected` naming the check that failed. The key that verifies the signature decides which
issuer the token may claim.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

SERVICE_ID: Final = "inkthread"
BASTION_ISS: Final = "bastion"
FRONTEND_ISS: Final = "inkthread-frontend"
FRONTEND_ROLE: Final = "frontend"
LEEWAY_S: Final = 10
MAX_LIFETIME_S: Final = 300
_ALGORITHM: Final = "EdDSA"
_SIGNATURE_ONLY: Final = {
    "verify_signature": True,
    "verify_exp": False,
    "verify_nbf": False,
    "verify_iat": False,
    "verify_aud": False,
    "verify_iss": False,
    "verify_sub": False,
    "verify_jti": False,
}


class TokenRejected(Exception):
    """The token failed `check`; the message never holds the token."""

    def __init__(self, check: str) -> None:
        self.check = check
        super().__init__(f"platform token failed the {check} check")


@dataclass(frozen=True, slots=True)
class TrustedKeys:
    """bastion's key and inkthread-frontend's key; either may be absent."""

    bastion: Ed25519PublicKey | None
    frontend: Ed25519PublicKey | None

    @property
    def any(self) -> bool:
        """Whether at least one key is configured."""
        return self.bastion is not None or self.frontend is not None


@dataclass(frozen=True, slots=True)
class Principal:
    """Who a valid token speaks for."""

    iss: str
    sub: str
    role: str

    @property
    def rate_key(self) -> str:
        """The rate-limit bucket of an authenticated caller (spec 12 § 3)."""
        return f"{self.iss}:{self.sub}"


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _claims(claims: dict[str, object], iss: str, now: float) -> Principal:
    """Every claim check after the signature, in spec order."""
    role = claims.get("role")
    if iss == FRONTEND_ISS and role != FRONTEND_ROLE:
        raise TokenRejected("role")
    aud = claims.get("aud")
    if not isinstance(aud, str) or aud != SERVICE_ID:
        raise TokenRejected("aud")
    exp, iat = claims.get("exp"), claims.get("iat")
    if not _is_int(exp):
        raise TokenRejected("exp")
    if not _is_int(iat):
        raise TokenRejected("iat")
    assert isinstance(exp, int)  # noqa: S101 - narrowed by _is_int for the type checker
    assert isinstance(iat, int)  # noqa: S101
    if exp + LEEWAY_S <= now:
        raise TokenRejected("exp")
    if iat - LEEWAY_S > now:
        raise TokenRejected("iat")
    if not 0 < exp - iat <= MAX_LIFETIME_S:
        raise TokenRejected("lifetime")
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub:
        raise TokenRejected("sub")
    return Principal(iss=iss, sub=sub, role=role if isinstance(role, str) else "")


def verify(token: str, keys: TrustedKeys, *, now: float) -> Principal:
    """The caller a token speaks for, or `TokenRejected`."""
    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError:
        raise TokenRejected("malformed") from None
    if header.get("alg") != _ALGORITHM:
        raise TokenRejected("alg")
    verified_by: list[str] = []
    for key, iss in ((keys.bastion, BASTION_ISS), (keys.frontend, FRONTEND_ISS)):
        if key is None:
            continue
        try:
            claims = jwt.decode(token, key, algorithms=[_ALGORITHM], options=_SIGNATURE_ONLY)  # type: ignore[arg-type]  # PyJWT types options as a TypedDict
        except jwt.InvalidSignatureError:
            continue
        except jwt.InvalidTokenError:
            raise TokenRejected("malformed") from None
        verified_by.append(iss)
        if claims.get("iss") == iss:
            return _claims(claims, iss, now)
    raise TokenRejected("iss" if verified_by else "signature")
