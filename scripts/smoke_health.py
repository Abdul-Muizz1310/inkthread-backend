"""Post-deploy smoke check (convention-ops-baseline): GET /health and /samples on SMOKE_BASE_URL.

Unset → print "skipping" and exit 0 without a single request, so a fork PR or a parked free
service can never turn CI red.
"""

from __future__ import annotations

import os
import sys
import time

import httpx


def samples_verdict(status: int, body: object) -> tuple[bool, str]:
    """Whether `/samples` answered as a healthy deploy does, and a line saying so.

    Behind the platform token (spec 12) a token-less probe gets `401 missing_platform_token`, which
    is the gate working; `503 platform_auth_unconfigured` means no key is set, a failed deploy.
    """
    detail = body.get("detail") if isinstance(body, dict) else None
    if status == 200 and isinstance(body, dict):
        return True, f"samples 200: {len(body.get('items', []))} items"
    if status == 401 and detail == "missing_platform_token":
        return True, "samples 401: gated by the platform token"
    return False, f"samples {status}: {detail or 'unexpected answer'}"


def main() -> int:
    base = os.environ.get("SMOKE_BASE_URL", "").strip().rstrip("/")
    if not base:
        print("SMOKE_BASE_URL unset; skipping")  # noqa: T201
        return 0
    deadline = time.monotonic() + 180
    while True:
        try:
            health = httpx.get(f"{base}/health", timeout=60)
            if health.status_code == 200 and health.json().get("db") == "ok":
                break
        except httpx.HTTPError:
            pass
        if time.monotonic() > deadline:
            print(f"health never came up at {base}")  # noqa: T201
            return 1
        time.sleep(10)
    samples = httpx.get(f"{base}/samples", timeout=60)
    try:
        body: object = samples.json()
    except ValueError:
        body = None
    ok, line = samples_verdict(samples.status_code, body)
    print(f"health ok; {line}")  # noqa: T201
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
