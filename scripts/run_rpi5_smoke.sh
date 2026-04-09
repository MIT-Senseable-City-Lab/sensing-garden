#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_NAME="${IMAGE_NAME:-bugcam-rpi5-smoke}"
DOCKERFILE="${DOCKERFILE:-$REPO_ROOT/docker/rpi5-smoke.Dockerfile}"
PLATFORM="${PLATFORM:-linux/arm64}"
DOCKER_HOST_DEFAULT="unix:///Users/${USER}/.docker/run/docker.sock"

if [[ -z "${DOCKER_HOST:-}" && -S "/Users/${USER}/.docker/run/docker.sock" ]]; then
  export DOCKER_HOST="$DOCKER_HOST_DEFAULT"
fi

if ! docker version >/dev/null 2>&1; then
  echo "Docker daemon is not reachable."
  echo "Start Docker Desktop, or export a working DOCKER_HOST, then rerun this script."
  exit 1
fi

docker build \
  --platform "$PLATFORM" \
  -f "$DOCKERFILE" \
  -t "$IMAGE_NAME" \
  "$REPO_ROOT"

docker run --rm \
  --platform "$PLATFORM" \
  "$IMAGE_NAME"
