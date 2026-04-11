#!/bin/bash
set -euo pipefail

# =============================================================================
# korbPuls Docker Image Build Script
# =============================================================================
# This script builds and optionally pushes the korbPuls Docker image.
# It supports both local builds and registry pushes (GHCR, Docker Hub, etc.)
#
# Usage:
#   ./scripts/build-docker.sh                  # Build locally only
#   ./scripts/build-docker.sh --push          # Build and push to registry
#   ./scripts/build-docker.sh --platform linux/amd64,linux/arm64  # Multi-platform
#   ./scripts/build-docker.sh --tag ghcr.io/user/korbpuls:latest # Custom tag
# =============================================================================

# Configuration
REGISTRY="${REGISTRY:-ghcr.io}"
IMAGE_NAME="${IMAGE_NAME:-korbpuls}"
OWNER="${OWNER:-malvavisc0}"
FULL_IMAGE_NAME="${REGISTRY}/${OWNER}/${IMAGE_NAME}"

# Default values
PUSH=false
PLATFORMS="linux/amd64"
TAGS=()

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --push)
            PUSH=true
            shift
            ;;
        --platform)
            PLATFORMS="$2"
            shift 2
            ;;
        --tag)
            TAGS+=("$2")
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --push                    Push image after building"
            echo "  --platform PLATFORMS      Target platforms (default: linux/amd64)"
            echo "                           Comma-separated for multi-platform"
            echo "  --tag IMAGE:TAG           Additional tag to apply"
            echo "  --help, -h                Show this help message"
            echo ""
            echo "Environment variables:"
            echo "  REGISTRY                  Container registry (default: ghcr.io)"
            echo "  IMAGE_NAME                Image name (default: korbpuls)"
            echo "  OWNER                     Owner/org (default: malvavisc0)"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Build version tag from git
VERSION=$(git describe --tags --always --dirty 2>/dev/null || echo "dev")
BUILD_DATE=$(date -u +'%Y-%m-%dT%H:%M:%SZ')

# Default tags if none specified
if [[ ${#TAGS[@]} -eq 0 ]]; then
    TAGS=("${FULL_IMAGE_NAME}:latest" "${FULL_IMAGE_NAME}:${VERSION}")
fi

echo "=============================================="
echo "korbPuls Docker Build Script"
echo "=============================================="
echo "Registry:   ${REGISTRY}"
echo "Image:      ${IMAGE_NAME}"
echo "Owner:      ${OWNER}"
echo "Version:    ${VERSION}"
echo "Build Date: ${BUILD_DATE}"
echo "Platforms:  ${PLATFORMS}"
echo "Tags:       ${TAGS[*]}"
echo "Push:       ${PUSH}"
echo "=============================================="

# Build arguments for docker
BUILD_ARGS=(
    --build-arg "BUILD_DATE=${BUILD_DATE}"
    --build-arg "VERSION=${VERSION}"
)

# Build the image
echo ""
echo ">>> Building Docker image..."

# Start building the command
DOCKER_CMD=(docker buildx build)

# Add platform
DOCKER_CMD+=(--platform="${PLATFORMS}")

# Add tags
for tag in "${TAGS[@]}"; do
    DOCKER_CMD+=(-t "${tag}")
done

# Add build args
DOCKER_CMD+=("${BUILD_ARGS[@]}")

# Determine output mode
if [[ "${PUSH}" == "true" ]]; then
    DOCKER_CMD+=(--push)
elif [[ "${PLATFORMS}" != *,* ]]; then
    # --load only works for single-platform builds
    DOCKER_CMD+=(--load)
else
    echo "WARNING: Multi-platform build without --push; images stay in build cache only."
fi

# Add context
DOCKER_CMD+=(.)

echo "Executing: ${DOCKER_CMD[*]}"
"${DOCKER_CMD[@]}"

echo ""
echo "=============================================="
echo "Build complete!"
echo "=============================================="
echo ""
echo "To run the image locally:"
echo "  docker run -d -p 8000:8000 \\"
echo "    -e KORBPULS_API_KEY=your_api_key \\"
echo "    ${TAGS[0]}"
echo ""
echo "Or using docker-compose:"
echo "  IMAGE=${TAGS[0]} docker-compose up"
echo ""
