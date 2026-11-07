#!/usr/bin/env bash
# One-command demo, no Docker: ingest a small repo (eval/fixture/repo), ask a
# question, stream a cited answer from a local Ollama model.
#
# Needs: python3 (3.10+), Ollama (https://ollama.com) installed. Runs retrieval-service
# with an in-memory Qdrant and gateway-api as local processes, then stops them.
# First run installs Python deps into .venv and downloads the embedding model
# (~90 MB) and the LLM (llama3.2:3b, ~2 GB); later runs reuse both.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD
MODEL="${DEMO_MODEL:-llama3.2:3b}"

command -v ollama >/dev/null || { echo "Ollama not found: install it from https://ollama.com" >&2; exit 1; }
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
  .venv/bin/pip install -q -r services/gateway-api/requirements.txt \
    -r services/retrieval-service/requirements.txt websockets
fi
PY=$ROOT/.venv/bin/python
for d in services/retrieval-service services/gateway-api; do
  $PY -m grpc_tools.protoc -I $d/proto --python_out=$d --grpc_python_out=$d $d/proto/retrieval.proto
done

pids=()
cleanup() { for p in "${pids[@]:-}"; do [ -n "$p" ] && kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT

if ! curl -sf http://localhost:11434/api/version >/dev/null; then
  ollama serve >/dev/null 2>&1 & pids+=($!)
  until curl -sf http://localhost:11434/api/version >/dev/null; do sleep 1; done
fi
ollama list | grep -q "^$MODEL" || ollama pull "$MODEL"

(cd services/retrieval-service && QDRANT_URL=:memory: INGEST_ALLOWED_ROOTS="$ROOT/eval/fixture" \
  EMBEDDING_DEVICE=cpu exec $PY server.py >"$ROOT/.venv/retrieval.log" 2>&1) & pids+=($!)
(cd services/gateway-api && GATEWAY_RETRIEVAL_GRPC_TARGET=localhost:50051 \
  GATEWAY_LLM_BASE_URL=http://localhost:11434/v1 GATEWAY_LLM_MODEL="$MODEL" \
  exec $PY -m uvicorn app.main:app --port 8000 >"$ROOT/.venv/gateway.log" 2>&1) & pids+=($!)
until curl -sf http://localhost:8000/livez >/dev/null; do sleep 1; done
until curl -sf http://localhost:9101 >/dev/null; do sleep 1; done

$PY scripts/demo.py --repo-path "$ROOT/eval/fixture/repo" "$@"
