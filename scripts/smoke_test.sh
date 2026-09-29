#!/bin/bash
# Quick end-to-end sanity check against a running docker-compose stack.
set -euo pipefail

GATEWAY_URL="${GATEWAY_URL:-http://localhost:8000}"

echo "== /healthz =="
curl -sf "$GATEWAY_URL/healthz" | tee /dev/stderr

echo
echo "== /token =="
TOKEN=$(curl -sf -X POST "$GATEWAY_URL/token" -d "username=admin&password=admin" | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')
echo "got token: ${TOKEN:0:12}..."

echo
echo "== /chat =="
curl -sf -X POST "$GATEWAY_URL/chat" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question": "What does this project do?"}'

echo
echo "smoke test passed"
