# Measured results

Every number in the top-level README comes from a command below or from `docs/evaluation.md`.
Re-run the commands to reproduce; numbers move a little between machines.

Environment for the runs in this directory: macOS 26 (Darwin 25.2), Apple M1 8 GB, Python 3.12.5,
grpcio 1.66.2, qdrant-client 1.11.3 (embedded), no GPU, no LLM, embedding model replaced by a
deterministic hash stand-in (these runs measure pipeline behaviour, not embedding quality).

## Test suite

| Command | Result |
|---|---|
| `make test` (gateway-api) | 139 passed, 1 skipped |
| `make test-retrieval` | 71 passed |
| `make test-integration` | 6 passed |
| `make test-eval` | 32 passed |
| `ruff check .` (ruff 0.14.0) | all checks passed |

## Agent reliability gate (no LLM)

`python eval/agent_eval.py --gate --report docs/results/agent_eval.md` -> [agent_eval.md](agent_eval.md).
Scripted model turns: it tests the gateway's guard and citation checks, not a model.

## Incremental ingest (`make bench-ingest`)

Hash stand-in embedder, temporary copy of this repo's tracked files, embedded Qdrant.

| Step | Files scanned | Files changed | Files removed | Chunks embedded | Chunks in index |
|---|---|---|---|---|---|
| first ingest | 129 | 125 | 0 | 637 | 637 |
| unchanged re-ingest | 129 | 0 | 0 | 0 | 637 |
| one file edited | 129 | 1 | 0 | 3 | 637 |
| one file deleted | 128 | 0 | 1 | 0 | 636 |

## gRPC channel reuse (`make bench-grpc`, 1000 calls, loopback)

| Pattern | p50 ms | p95 ms | p99 ms | mean ms |
|---|---|---|---|---|
| new channel per call | 0.720 | 1.365 | 2.215 | 0.787 |
| shared channel | 0.267 | 0.423 | 0.754 | 0.292 |

## Retrieval quality

Not re-run in this pass (needs the real embedding model and a Qdrant server). The 22-question
ablation in `docs/evaluation.md` (produced by `make eval`) is the source of the Recall@5 / MRR figures.
CI re-checks a 5-question fixture (Recall >= 0.8) on every push.

## Not measured

Live-LLM answer quality (grounded-citation rate, abstention), latency of a real local model on an 8 GB Mac.
