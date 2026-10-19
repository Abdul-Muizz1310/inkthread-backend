"""Router dependencies: the shared services and configuration, the client address, admin auth."""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, Request

from inkthread.core.config import Settings
from inkthread.core.errors import AdminDisabled, AdminTokenInvalid, AdminTokenRequired
from inkthread.core.ratelimit import SlidingWindow
from inkthread.platform.token import Principal
from inkthread.services.container import Services


@dataclass(frozen=True)
class ApiConfig:
    """What the HTTP layer needs beyond the services."""

    settings: Settings
    limiter: SlidingWindow
    ping_interval_s: float
    stream_max_s: float


def get_services(request: Request) -> Services:
    """The services the lifespan built."""
    services = getattr(request.app.state, "services", None)
    if not isinstance(services, Services):  # pragma: no cover - the lifespan always sets it
        msg = "the app's lifespan has not run"
        raise TypeError(msg)
    return services


def get_config(request: Request) -> ApiConfig:
    """The app's HTTP configuration."""
    config = getattr(request.app.state, "config", None)
    if not isinstance(config, ApiConfig):  # pragma: no cover - create_app always sets it
        msg = "the app was not built by create_app"
        raise TypeError(msg)
    return config


def client_ip(request: Request) -> str:
    """The caller's address (uvicorn applies the proxy headers in production)."""
    return request.client.host if request.client else "unknown"


def rate_key(request: Request) -> str:
    """The upload limiter's bucket: `iss:sub` for a token's caller, else the address (spec 12)."""
    principal = getattr(request.state, "principal", None)
    if isinstance(principal, Principal):
        return principal.rate_key
    return client_ip(request)


def require_admin(
    config: Annotated[ApiConfig, Depends(get_config)],
    x_admin_token: Annotated[str | None, Header()] = None,
) -> None:
    """Admin routes fail closed: 503 without a configured token, 401 without one, 403 if wrong."""
    expected = config.settings.admin_token
    if expected is None or not expected.get_secret_value():
        raise AdminDisabled
    if not x_admin_token:
        raise AdminTokenRequired
    if not hmac.compare_digest(
        x_admin_token.encode("utf-8"), expected.get_secret_value().encode("utf-8")
    ):
        raise AdminTokenInvalid


ServicesDep = Annotated[Services, Depends(get_services)]
ConfigDep = Annotated[ApiConfig, Depends(get_config)]
AdminDep = Depends(require_admin)
