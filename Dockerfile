FROM python:3.12-slim

WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY alembic ./alembic
COPY alembic.ini docker-entrypoint.sh ./
COPY samples ./samples
RUN uv sync --frozen --no-dev && useradd --create-home --uid 10001 app \
    && mkdir -p /app/var && chown -R app /app/var
USER app

# Left empty on purpose: /health falls through to Render's RENDER_GIT_COMMIT.
ARG COMMIT_SHA=""
ENV COMMIT_SHA=${COMMIT_SHA} PATH="/app/.venv/bin:${PATH}"

EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["sh", "-c", "uvicorn inkthread.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips '*'"]
