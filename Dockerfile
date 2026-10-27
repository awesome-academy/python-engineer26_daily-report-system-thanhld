# syntax=docker/dockerfile:1
FROM python:3.13-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# true: cài thêm nhóm dependency "debug" (debugpy). Chỉ bật cho image dev (docker-compose.yml).
ARG INSTALL_DEBUGPY=false

# Cài dependency trước để tận dụng cache khi chỉ sửa code.
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project \
        $([ "$INSTALL_DEBUGPY" = "true" ] && echo --group debug)

COPY README.md alembic.ini ./
COPY migrations ./migrations
COPY scripts ./scripts
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev $([ "$INSTALL_DEBUGPY" = "true" ] && echo --group debug)

RUN useradd --system --uid 1001 --no-create-home app
USER app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
