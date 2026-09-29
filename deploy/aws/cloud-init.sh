#!/bin/bash
# Cloud-init / user-data script for a single EC2 instance running the whole
# stack via docker-compose. Suitable for a t3.large+ (CPU-only; point
# GATEWAY_OLLAMA_URL at a separate edge/GPU box for real inference load,
# see services/edge-inference/README.md).
set -euo pipefail

apt-get update -y
apt-get install -y docker.io docker-compose-plugin git
systemctl enable --now docker

REPO_URL="${REPO_URL:-https://github.com/<your-username>/codesage-agent.git}"
INSTALL_DIR="/opt/codesage-agent"

if [ ! -d "$INSTALL_DIR" ]; then
  git clone "$REPO_URL" "$INSTALL_DIR"
fi
cd "$INSTALL_DIR"

cp -n .env.example .env || true

docker compose pull || true
docker compose up -d --build
