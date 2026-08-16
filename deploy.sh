#!/usr/bin/env bash
# Deploy script for the MailAfrica Agent — invoked by the restricted SSH key
# (GitHub Actions deploy.yml) as the forced command.
set -euo pipefail

cd "$(dirname "$0")"
PROJECT_DIR="$(pwd)"

echo "[deploy] pulling $PROJECT_DIR"
git pull --ff-only origin main

echo "[deploy] installing dependencies (uv)"
if command -v uv >/dev/null 2>&1; then
  uv sync --frozen
else
  echo "uv is not installed — run: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  exit 1
fi

echo "[deploy] restarting services"
if systemctl is-active --quiet mailafrica-agent-webhook; then
  systemctl restart mailafrica-agent-webhook
else
  echo "[deploy] mailafrica-agent-webhook is not active — is it installed? (see deploy/setup_vps.sh)" >&2
fi

echo "[deploy] done"
