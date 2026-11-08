#!/usr/bin/env bash
# Retrieval ablation with no Docker: runs retrieval-service with an in-memory Qdrant,
# ingests a clean `git archive` of HEAD (tracked files only, so it does not depend on
# local clutter such as .venv), runs eval/ablation.py (dense / lexical / hybrid /
# hybrid + rerank over every question in eval/qa_pairs.jsonl) and writes eval/report.md.
#
# Needs the retrieval-service and eval requirements installed in the active Python
# (PYTHON=... to override). The first run downloads the embedding and reranker models.
# The reranked pass is slow on CPU (minutes).
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD
PY="${PYTHON:-python3}"
WORK=$(mktemp -d)
pid=""
cleanup() { [ -n "$pid" ] && kill "$pid" 2>/dev/null || true; rm -rf "$WORK"; }
trap cleanup EXIT

$PY -m grpc_tools.protoc -I services/retrieval-service/proto \
  --python_out=services/retrieval-service --grpc_python_out=services/retrieval-service \
  services/retrieval-service/proto/retrieval.proto
$PY -m grpc_tools.protoc -I services/retrieval-service/proto \
  --python_out=eval --grpc_python_out=eval services/retrieval-service/proto/retrieval.proto

mkdir "$WORK/corpus"
git archive HEAD | tar -x -C "$WORK/corpus"
SHA=$(git rev-parse --short HEAD)

(cd services/retrieval-service && QDRANT_URL=:memory: INGEST_ALLOWED_ROOTS="$WORK/corpus" \
  EMBEDDING_DEVICE=cpu exec $PY server.py >"$WORK/retrieval.log" 2>&1) & pid=$!
until curl -sf http://localhost:9101 >/dev/null; do
  kill -0 "$pid" 2>/dev/null || { cat "$WORK/retrieval.log" >&2; exit 1; }
  sleep 1
done

$PY - "$WORK/corpus" <<'PY'
import sys
import grpc
sys.path.insert(0, "services/retrieval-service")
import retrieval_pb2, retrieval_pb2_grpc
stub = retrieval_pb2_grpc.RetrievalStub(grpc.insecure_channel("localhost:50051"))
resp = stub.IngestRepo(retrieval_pb2.IngestRequest(repo_path=sys.argv[1], collection="codebase"), timeout=900)
print("ingested", resp.chunks_indexed, "chunks from", resp.files_indexed, "files")
sys.exit(0 if resp.chunks_indexed else "ingest indexed no chunks")
PY

cd eval && $PY ablation.py --note "git archive of commit $SHA, in-memory Qdrant, CPU embeddings"
