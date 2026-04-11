# --- builder ---
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src/ src/
RUN uv sync --frozen --no-dev

# --- runtime ---
FROM python:3.12-slim AS runtime

ARG BUILD_DATE
ARG VERSION

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

LABEL org.opencontainers.image.title="korbPuls" \
      org.opencontainers.image.description="Basketball league dashboard" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.source="https://github.com/malvavisc0/korbpuls"

EXPOSE 8000
VOLUME ["/data/cache"]

ENTRYPOINT ["./run.sh"]
