# CodeSage

CodeSage is a coding assistant that answers questions about a codebase. It indexes a repository, retrieves relevant chunks for a question, and generates an answer with file and line citations, using a local LLM rather than a hosted API.

It has three parts that work together:

- A retrieval pipeline that combines vector search and keyword search, with optional reranking and an evaluation harness to measure whether each piece actually helps.
- A bounded agent loop that can call tools (search the code, pull more context, read a whole file) across a few steps before answering, instead of a single retrieve-then-answer pass.
- A small deployment stack around both: gRPC between services, JWT auth, an API gateway, metrics, Docker Compose and Kubernetes manifests, and support for three different local LLM backends.

## How it works

1. A question comes in over REST, WebSocket, or the agent endpoint.
2. `gateway-api` calls `retrieval-service` over gRPC. By default it searches a vector index (Qdrant); it can also fuse in a keyword index (BM25) and rerank with a cross-encoder, both off by default because they measured no better than dense search alone on this corpus (see `docs/evaluation.md`). Either way, it assembles a token-budgeted context without cutting any chunk in half.
3. The context and question go to a local LLM: Ollama, vLLM, or llama.cpp, chosen by an environment variable, all behind one client that speaks the OpenAI-compatible chat completions API.
4. The answer streams back with citations in `[file:start-end]` format.

The agent endpoint (`POST /agent`) adds a loop on top of this: the model can call `search_code`, `expand_context`, or `get_file` up to a few times before producing a final answer, bounded by a step limit, a tool-call limit, and a hard deadline. Every citation in the final answer is checked against what the tools actually returned in that run, and the response lists which citations are grounded and which the model made up.

Ingestion is incremental: each chunk records a hash of its file, so re-indexing a repository only re-embeds files that changed and deletes chunks of files that were removed. Qdrant is the only durable store; the in-memory keyword index is rebuilt from it after a restart.

## Stack

| Concern | Choice |
|---|---|
| Backend | Python, FastAPI |
| Internal RPC | gRPC (`proto/retrieval.proto`) |
| Client protocols | REST (`/chat`, `/agent`), WebSocket (`/ws/chat`) |
| Retrieval | Qdrant (dense, default), optional bm25s (lexical) fusion and cross-encoder rerank |
| Agent | A small bounded tool-calling loop, no agent framework |
| Local LLM serving | Ollama, vLLM, or llama.cpp behind one OpenAI-compatible client |
| API gateway | Traefik |
| Auth | JWT |
| Monitoring | Prometheus + Grafana |
| Containers | Docker Compose and Kubernetes manifests, with resource limits and health-gated startup |
| Cloud deploy | Single-VM scripts for AWS, GCP, Azure |
| CI | GitHub Actions: unit tests, a retrieval quality gate, Docker builds, Compose/k8s validation |

## Running it

```bash
cp .env.example .env
make up                 # docker compose up -d --build
make pull-model          # ollama pull llama3.1:8b-instruct-q4_0
make ingest-self         # index this repo as the demo corpus
make smoke               # curl through /healthz, /token, /chat
```

Then:
- API: `http://localhost:8000` directly, or `http://localhost` through Traefik
- Grafana: `http://localhost:3000` (`admin` / the value of `GRAFANA_ADMIN_PASSWORD`)
- Prometheus: `http://localhost:9090`
- Qdrant dashboard: `http://localhost:6333/dashboard`

On a machine with an NVIDIA GPU, use `make up-gpu` instead of `make up`. To use vLLM or llama.cpp instead of Ollama: `make up-vllm` or `make up-llamacpp`. See `docs/architecture.md` for what each backend needs and what has actually been tested.

## Design decisions

Each of these is a short record of the options, what was chosen, and what it costs, in `docs/adr/`:

- [0001](docs/adr/0001-grpc-between-gateway-and-retrieval.md) gRPC between the gateway and retrieval, with a shared channel and retries only on `UNAVAILABLE`
- [0002](docs/adr/0002-dense-retrieval-by-default.md) Dense retrieval by default, because hybrid fusion measured no better on this corpus
- [0003](docs/adr/0003-native-agent-loop.md) A bounded native agent loop instead of an agent framework
- [0004](docs/adr/0004-idempotent-incremental-ingestion.md) Idempotent, incremental ingestion with Qdrant as the only durable store
- [0005](docs/adr/0005-in-process-tracing-not-opentelemetry.md) In-process trace spans and Prometheus, not OpenTelemetry yet

## Measured results

| What | Result | Source |
|---|---|---|
| Retrieval quality, 22 questions on this repo | Dense Recall@5 0.70, MRR 0.51; hybrid 0.70 / 0.45; hybrid + rerank 0.80 / 0.49 at ~25x latency | `docs/evaluation.md` |
| Re-ingesting an unchanged repo (105 files, 353 chunks) | 0 chunks embedded (previously all 353, written as a duplicate copy of every point) | `scripts/bench_ingest.py`, ADR 0004 |
| Re-ingesting after editing one file (README.md) | 3 chunks embedded | `scripts/bench_ingest.py` |
| gRPC call overhead, new channel per call vs shared (loopback, 1000 calls) | p50 0.57 ms to 0.24 ms, p99 0.77 ms to 0.29 ms | `scripts/bench_grpc_channel.py` |

## Tests and evaluation

```bash
make test              # gateway-api unit tests
make test-retrieval    # retrieval-service unit tests
make test-eval          # eval harness unit tests
make test-integration   # gateway + retrieval-service over real gRPC, no Docker
make eval               # retrieval evaluation: Recall@K, MRR, an ablation report
```

`make bench-grpc` and `make bench-ingest` run the two benchmarks above. The retrieval-service tests run ingestion and search against an embedded Qdrant (no server), with only the embedding model swapped for a deterministic stand-in. Unit tests and a small retrieval-quality gate also run in CI. See `docs/evaluation.md` for what the evaluation harness measures and what it found.

## Repository layout

```
services/
  gateway-api/          FastAPI: REST, WebSocket, agent loop, JWT auth, metrics
  retrieval-service/    gRPC: chunking, embedding, dense/hybrid search, reranking
  edge-inference/       compose override for running inference on a separate machine
eval/                   retrieval evaluation harness and benchmark questions
gateway/traefik/        reverse proxy config
monitoring/             Prometheus scrape config and Grafana dashboard
k8s/                    Kubernetes manifests
deploy/aws, gcp, azure/ single-VM cloud deployment scripts
docs/                   architecture, evaluation, and design decision records (adr/)
scripts/                ingestion, quantization, smoke-test, and benchmark helpers
```

## Status

This is a demo project, not a production service. Known limitations:

- Auth uses a single demo user from environment variables, and the default JWT secret is a placeholder you must override.
- There is no TLS termination configured.
- There is no multi-turn memory: each question is answered on its own.
- The retrieval benchmark is 22 questions on one corpus, and only the Ollama backend has been tested live for tool calling.
- A retrieval replica that has already built its keyword index will not see an ingest done through another replica until it restarts (this only affects the non-default hybrid and lexical modes).

`docs/architecture.md` covers these where they matter.

## License

[MIT](LICENSE)
