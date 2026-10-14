"""Run Alembic in a subprocess against a database URL, as the container entrypoint does."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def migrate(url: str, target: str = "head", *, down: bool = False) -> None:
    env = {**os.environ, "DATABASE_URL": url, "LLM_MODE": "off"}
    cmd = [sys.executable, "-m", "alembic", "downgrade" if down else "upgrade", target]
    done = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise RuntimeError(done.stderr)
