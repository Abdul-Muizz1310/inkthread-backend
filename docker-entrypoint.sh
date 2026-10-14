#!/bin/sh
# Bring the schema to head, then start the server. Render's free plan ignores
# preDeployCommand, so the container is the only place migrations can run on every
# deploy (knowledge: infra-deployment-mechanics). `alembic upgrade head` is
# idempotent, and a failure aborts startup on purpose.
set -e
if [ -n "${DATABASE_URL:-}" ]; then
  echo "[entrypoint] alembic upgrade head"
  /app/.venv/bin/alembic upgrade head
fi
exec "$@"
