"""Post-deploy smoke check (convention-ops-baseline): GET /health and /samples on SMOKE_BASE_URL.

Unset → print "skipping" and exit 0 without a single request, so a fork PR or a parked free
service can never turn CI red.
"""

from __future__ import annotations

import os
import sys
import time

import httpx


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
    print(f"health ok; samples {samples.status_code}: {len(samples.json().get('items', []))} items")  # noqa: T201
    return 0 if samples.status_code == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
