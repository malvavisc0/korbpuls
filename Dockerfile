# --- builder ---
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY src/ src/

# --- runtime ---
FROM python:3.12-slim AS runtime

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
COPY run.sh ./
RUN chmod +x run.sh

ENV PATH="/app/.venv/bin:$PATH"
ENV KORB_CMD="korb"
ENV CACHE_DIR="/data/cache"
ENV PORT="8000"
ENV WORKERS="2"
ENV RUNNER=""

EXPOSE 8000
VOLUME ["/data/cache"]

ENTRYPOINT ["./run.sh"]
