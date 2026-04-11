# Docker Distribution for korbPuls

## Overview

korbPuls is distributed as a multi-platform Docker image via GitHub Container Registry (GHCR).

## Prerequisites

- `uv.lock` **must** be committed to git (required by `uv sync --frozen` in the Dockerfile)
- Docker with [Buildx](https://docs.docker.com/buildx/working-with-buildx/) for multi-platform builds

## Components

### 1. Dockerfile

Multi-stage build using `uv` for fast, reproducible installs:

| Stage     | Purpose                                     |
|-----------|---------------------------------------------|
| `builder` | Installs dependencies via `uv sync --frozen --no-dev` |
| `runtime` | Minimal `python:3.12-slim` with `.venv` + app source |

**Environment variables** (configurable at runtime):

| Variable              | Default        | Description                          |
|-----------------------|----------------|--------------------------------------|
| `KORBPULS_API_KEY`    | *(required)*   | API key for korb backend             |
| `KORB_CMD`            | `korb`         | Path to korb CLI                     |
| `CACHE_DIR`           | `/data/cache`  | Persistent cache directory           |
| `PORT`                | `8000`         | HTTP listen port                     |
| `WORKERS`             | `2`            | Uvicorn worker count                 |
| `RUNNER`              | `""` (empty)   | Command prefix — empty = direct exec |
| `OPENAILIKE_API_BASE` | *(optional)*   | AI provider base URL                 |
| `OPENAILIKE_API_KEY`  | *(optional)*   | AI provider API key                  |
| `OPENAILIKE_LLM`      | *(optional)*   | AI model name                        |

> **Note:** `RUNNER` is set to empty string in the Dockerfile so the container runs
> `uvicorn` directly from the virtualenv. For local development (outside Docker),
> `run.sh` defaults to `uv run` when `RUNNER` is unset.

### 2. Local Build Script ([`scripts/build-docker.sh`](scripts/build-docker.sh))

Bash script for building and optionally pushing the Docker image locally.

**Features:**
- Multi-platform builds via `docker buildx` (`linux/amd64`, `linux/arm64`)
- `--push` flag integrates directly with buildx (no separate push step)
- `--load` is used automatically for local single-platform builds
- Extracts version from git tags; sets OCI image labels

**Usage:**
```bash
# Build locally (single-platform, loaded into docker daemon)
./scripts/build-docker.sh

# Build and push to GHCR
./scripts/build-docker.sh --push

# Multi-platform build and push
./scripts/build-docker.sh --platform linux/amd64,linux/arm64 --push

# Custom tag
./scripts/build-docker.sh --tag myregistry.com/korbpuls:v1.0.0
```

### 3. GitHub Actions Workflow ([`.github/workflows/docker-publish.yml`](.github/workflows/docker-publish.yml))

Automates building, pushing, signing, and generating SBOMs on release.

**Triggers:**
- Push of tags matching `v*` (e.g., `v1.0.0`)
- GitHub Release publication
- Manual workflow dispatch

**Jobs:**

| Job              | Purpose                                    |
|------------------|--------------------------------------------|
| `build-and-push` | Multi-platform build, push to GHCR         |
| `sbom`           | Generate SPDX SBOM, upload as artifact     |
| `sig`            | Keyless Cosign signature via Sigstore OIDC  |

**Required permissions:**

| Job              | Permission            | Purpose                              |
|------------------|-----------------------|--------------------------------------|
| `build-and-push` | `packages: write`     | Push to GHCR                         |
| `sbom`           | `security-events: write` | Upload SBOM                       |
| `sbom`           | `packages: read`      | Pull image for scanning              |
| `sig`            | `id-token: write`     | OIDC token for keyless Cosign        |
| `sig`            | `packages: write`     | Attach signature to image            |

**Tag strategy:**
- `1.0.0` — semver (from `v1.0.0` tag, `v` prefix stripped)
- `1.0` — major.minor
- `<sha>` — commit SHA
- `latest` — applied on any `v*` tag push

## Usage After Publishing

### Pull the image
```bash
docker pull ghcr.io/malvavisc0/korbpuls:latest
```

### Run with Docker
```bash
docker run -d -p 8000:8000 \
  -e KORBPULS_API_KEY=your_api_key \
  -v korbpuls-cache:/data/cache \
  ghcr.io/malvavisc0/korbpuls:latest
```

### Run with Docker Compose

The included [`docker-compose.yml`](docker-compose.yml) is pre-configured to pull from GHCR:

```bash
# Create a .env file with your API key
echo "KORBPULS_API_KEY=your_api_key" > .env

# Start the service
docker compose up -d
```

The compose file pulls `ghcr.io/malvavisc0/korbpuls:latest`, maps port `8000`,
and persists the cache to a named volume. AI settings are optional — leave
`OPENAILIKE_*` vars empty in `.env` to disable AI features.

## Release Checklist

1. Ensure `uv.lock` is committed and up-to-date (`uv lock`)
2. Tag the release: `git tag v1.0.0 && git push origin v1.0.0`
3. The workflow automatically builds, pushes, signs, and generates the SBOM
4. Verify at `ghcr.io/malvavisc0/korbpuls`
