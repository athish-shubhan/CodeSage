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

The agent endpoint (`POST /agent`) adds a loop on top of this: the model can call `search_code`, `expand_context`, or `get_file` up to a few times before producing a final answer, bounded by a step limit, a tool-call limit, and a timeout.

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

## Tests and evaluation

```bash
make test              # gateway-api unit tests
make test-retrieval    # retrieval-service unit tests
make test-eval          # eval harness unit tests
make eval               # retrieval evaluation: Recall@K, MRR, an ablation report
```

Unit tests and a small retrieval-quality gate also run in CI. See `docs/evaluation.md` for what the evaluation harness measures and what it found.

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
docs/                   architecture and evaluation write-ups
scripts/                ingestion, quantization, and smoke-test helpers
```

## Status

This is a demo project, not a production service. Auth uses a single hardcoded demo user, there is no TLS termination configured, and agent/conversation state lives in memory on a single replica. These and other limitations are called out in `docs/architecture.md` where they matter, rather than hidden.

## License

[MIT](LICENSE)
