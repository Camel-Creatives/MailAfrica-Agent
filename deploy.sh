#!/usr/bin/env bash
# Deploy script for the MailAfrica Agent — invoked by GitHub Actions or deploy key.
set -euo pipefail

cd "$(dirname "$0")"
PROJECT_DIR="$(pwd)"

echo "[deploy] pulling latest main branch in $PROJECT_DIR"
git pull --ff-only origin main

if command -v docker >/dev/null 2>&1 && [ -f "docker-compose.yml" ]; then
  echo "[deploy] deploying container via Docker Compose..."
  docker compose up -d --build
elif systemctl is-active --quiet mailafrica-agent-webhook; then
  echo "[deploy] installing dependencies (uv)..."
  if command -v uv >/dev/null 2>&1; then
    uv sync --frozen
  fi
  echo "[deploy] restarting systemd service..."
  systemctl restart mailafrica-agent-webhook
else
  echo "[deploy] starting Docker Compose..."
  docker compose up -d --build
fi

echo "[deploy] deployment complete!"
