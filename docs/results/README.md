# Measured results

Every number in the top-level README comes from a command below or from `docs/evaluation.md`.
Re-run the commands to reproduce; numbers move a little between machines.

Environment for the runs in this directory: macOS 26 (Darwin 25.2), Apple M1 8 GB, Python 3.12.5,
grpcio 1.66.2, qdrant-client 1.11.3 (embedded), no GPU. The test, ingest and gRPC runs below use no LLM and a
deterministic hash stand-in for the embedding model (they measure pipeline behaviour, not embedding quality); the retrieval and live-agent runs further down use real models.

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

## Retrieval quality (`make eval-local`)

Real embedding model (`all-MiniLM-L6-v2`) and reranker, in-memory Qdrant, 28 questions (20 answerable, 8 unanswerable) over a `git archive` of commit `db35040` (136 files, 657 chunks), one run on the M1 above. Raw output: `eval/report.md`; the table and its reading are in `docs/evaluation.md`.

| Strategy | Recall@5 (n=20) | MRR | p50 latency |
|---|---|---|---|
| dense | 0.60 | 0.47 | 10 ms |
| lexical | 0.60 | 0.37 | 1 ms |
| hybrid | 0.70 | 0.55 | 11 ms |
| hybrid + rerank | 0.60 | 0.47 | 1134 ms |

CI also re-checks a 5-question fixture (Recall >= 0.8) on every push.

## Live agent eval (`make eval-agent LIVE=1`)

`llama3.2:3b` through Ollama on the same M1, one run, 12 cases (fixture repo): [agent_eval_live.md](agent_eval_live.md), per-case answers in [agent_eval_live.json](agent_eval_live.json). The numbers and their caveats are in the top-level README.

## Not measured

Latency of a larger local model on an 8 GB Mac (`qwen2.5:7b` took 159 s on one answer and was wrong, one observation, not a benchmark).
