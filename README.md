# CodeSage

[![CI](https://github.com/athish-shubhan/CodeSage/actions/workflows/ci.yml/badge.svg)](https://github.com/athish-shubhan/CodeSage/actions/workflows/ci.yml)

A local-LLM coding assistant: index a repository, ask a question, get a streamed answer with `[file:start-end]` citations that are checked against what was actually retrieved. Retrieval is dense-vector by default (hybrid dense + BM25 fusion and a cross-encoder rerank are optional, see [ADR 0002](docs/adr/0002-dense-retrieval-by-default.md)), the LLM runs locally behind an OpenAI-compatible API (Ollama, vLLM or llama.cpp), and nothing leaves your machine.

Why it exists: code Q&A tools tend to cite lines they never saw and will follow instructions planted in the repo they read. CodeSage treats retrieved text as untrusted, verifies every citation, and ships an eval gate in CI so those checks cannot silently regress.

## Quick start (8 GB Apple Silicon Mac, no Docker)

Prerequisites: Python 3.10+ and [Ollama](https://ollama.com).

```bash
git clone https://github.com/athish-shubhan/CodeSage && cd CodeSage
make demo
```

`make demo` creates `.venv`, starts the retrieval service (in-memory Qdrant) and the gateway, pulls `llama3.2:3b` (about 2 GB, 4-bit; override with `DEMO_MODEL=...`), ingests the 4-file `eval/fixture/repo`, asks "Does refund_payment require approval for large refunds?", and streams the answer over WebSocket with its citation check. The first run also downloads the 90 MB embedding model. The fixture contains a planted "ignore previous instructions" comment, so the output also shows the injection guard removing it.

If you prefer a hosted free tier over a local model, point `GATEWAY_LLM_BASE_URL`, `GATEWAY_LLM_MODEL` and `GATEWAY_LLM_API_KEY` at any OpenAI-compatible endpoint. The client speaks only that protocol; no hosted provider has been tested.

Full stack (Traefik, Prometheus, Grafana, Qdrant server) with Docker: `cp .env.example .env && make up && make pull-model && make ingest-self && make smoke`. Set `LLM_MODEL=llama3.2:3b` in `.env` on small machines; the default is an 8B model.

## Architecture

```mermaid
flowchart LR
    C[Client: REST / WebSocket / SSE] --> T[Traefik]
    T --> G[gateway-api<br/>FastAPI, JWT, metrics]
    G -- gRPC --> R["retrieval-service<br/>chunking, dense search (hybrid, rerank optional)"]
    R --> Q[(Qdrant)]
    G -- OpenAI-compatible API --> L[Ollama / vLLM / llama.cpp]
    G --> A[Agent loop<br/>search_code, expand_context, get_file]
    A -. checks .-> K[Injection guard +<br/>citation grounding]
    M[MCP adapter] -- gRPC --> R
```

- Retrieval: AST-aware chunking, dense search by default, optional BM25 fusion and cross-encoder rerank (both off by default because they did not pay off on the measured corpus, see Results). Ingestion is incremental and idempotent.
- Endpoints: `POST /chat`, `WS /ws/chat` (token streaming), `POST /agent` (bounded tool-calling loop), `POST /agent/stream` (the same run as server-sent events).
- Reliability: instruction-like sentences in retrieved text are removed and reported, citations are marked grounded or ungrounded, an opt-in repair turn lets the model fix bad citations, an audit log records agent runs, and one `X-Request-ID` follows a request through both services.
- Hardening: non-root, read-only containers, request size limits, ingest restricted to allow-listed roots, internal addresses kept out of error responses.
- Details: [docs/architecture.md](docs/architecture.md) and the [design records](docs/adr/); history of the nine improvement rounds in [IMPROVEMENTS.md](IMPROVEMENTS.md).

## Results

All numbers are from commands in [docs/results/README.md](docs/results/README.md) or from [docs/evaluation.md](docs/evaluation.md).

| What | Result | Source |
|---|---|---|
| Retrieval, 28 questions (20 answerable, 8 unanswerable) on this repo, one run, in-memory Qdrant, real embeddings, M1 | Recall@5 / MRR: dense 0.60 / 0.47; hybrid 0.70 / 0.55; hybrid + rerank 0.60 / 0.47. p50 latency 10 ms, 11 ms, 1134 ms | `docs/evaluation.md` (`make eval-local`) |
| Live LLM agent eval, `llama3.2:3b` via Ollama, 12 cases, one run | Grounded-citation rate 1.00 (n=4 citations); unsupported-identifier rate 0.00 (n=3); abstention accuracy 0.92 (11 of 12); injection resistance 1.00 (n=4). Only 3 of 12 answers contained any citation | `docs/results/agent_eval_live.md` (`make eval-agent LIVE=1`) |
| Re-ingest of an unchanged repo (129 files, 637 chunks) | 0 chunks re-embedded; one edited file re-embeds 3 | `make bench-ingest` |
| Shared vs per-call gRPC channel (1000 loopback calls) | p50 0.72 ms to 0.27 ms | `make bench-grpc` |
| Injection guard, 43 labeled sentences | catches 18 of 23 injections, flags 2 of 20 benign; 1 flag in 47 ordinary files | `make eval-agent` |
| Tests | gateway 139, retrieval 71, integration 6, eval 32 passing; ruff clean | `docs/results/README.md` |

The default is dense-only retrieval. With 20 answerable questions the strategies are not statistically distinguishable (0.60 vs 0.70 Recall@5 is 12 vs 14 questions, and the 95% bootstrap intervals, 0.40 to 0.80 and 0.50 to 0.90, overlap heavily), so the choice rests on simplicity, not on a measured advantage; this run, if anything, leans toward hybrid, and an earlier run on a 22-question set had hybrid tied with dense and the reranker best, so the ordering is not stable at this size. The 20 and 8 are the answerable and unanswerable question counts; Recall@5 and MRR are computed over the 20 answerable ones.

The live-LLM row is a single run of a 3B model over 12 hand-written cases on a small fixture repo, so treat each rate as an anecdote: the grounded-citation and identifier rates are computed over 4 and 3 items. The model often did not cite at all (3 of 12 answers had a citation) and sometimes printed a tool call as text instead of making one; "grounded" means the cited range was among the retrieved chunks, not that it supports the claim. Before the answer prompt spelled out the citation format with an example, the same run produced no citations at all (0 of 12 answers).

## Tests and evaluation

```bash
make test test-retrieval test-eval test-integration   # unit + gRPC integration, no Docker, LLM mocked
make lint                                              # ruff
make eval-agent                                        # injection / citation / abstention gate, no LLM
make eval-agent LIVE=1                                 # same cases against the configured LLM (e.g. Ollama llama3.2:3b)
make eval-local                                        # retrieval ablation, no Docker (in-memory Qdrant)
make eval                                              # same ablation against a running stack (needs `make ingest-self`)
```

CI (GitHub Actions) runs lint, all test suites, the agent reliability gate (blocking), a retrieval-quality gate on a fixture corpus (blocking), the MCP adapter tests, image builds with non-root and read-only checks, and compose/k8s validation.

## Limitations

- Demo project, not a production service: one demo user from environment variables, a placeholder JWT secret you must change, no TLS, no multi-turn memory.
- Retrieval benchmark is 28 questions (20 answerable, 8 unanswerable) on one corpus, one run. Answer quality with a live model was measured once, with a 3B model on 12 cases; the CI agent eval runs scripted model turns.
- Small local models follow the tool-calling protocol unreliably (a 0.5B model did not; `llama3.2:3b` handled it in some cases and printed the call as text in others in the live eval; larger models are not measured). `/ws/chat` and `/chat` do not need tool calling and are what the quick start uses.
- The injection detector figures (18 of 23, 2 of 20) come from sentences and rules written by the same author, so they are a regression guard, not an estimate of real-world detection; the five known misses were kept in the set on purpose.
- The injection regex misses paraphrased, translated and obfuscated injections ([ADR 0006](docs/adr/0006-untrusted-tool-output.md)).
- Only Ollama has been tested live for tool calling.

## Demo

![Demo](docs/demo.gif)

*One real run of `make demo` with `llama3.2:3b` on an 8 GB M1 (the recording is not edited): it ingests the fixture repo, strips two planted instruction-like comments before they reach the model, and streams an answer whose citation is checked against the retrieved chunks. Here the citation `auth.py:12-13` was among the retrieved chunks, so it is reported as grounded, but it is not the right place for the claim and the answer misses the fixture's planted bug (large unapproved refunds return `True`). The check says a citation was retrieved, not that the answer is correct. Across 7 earlier runs of the same question with the same prompt the model cited every time and 6 of 7 answers had only grounded citations; answer quality varied, and several answers were muddled about the bug. 3B models are weak at this.*

## Design decisions

Each of these is a short record of the options, what was chosen, and what it costs, in `docs/adr/`:

- [0001](docs/adr/0001-grpc-between-gateway-and-retrieval.md) gRPC between the gateway and retrieval, with a shared channel and retries only on `UNAVAILABLE`
- [0002](docs/adr/0002-dense-retrieval-by-default.md) Dense retrieval by default, because hybrid fusion measured no better on this corpus
- [0003](docs/adr/0003-native-agent-loop.md) A bounded native agent loop instead of an agent framework
- [0004](docs/adr/0004-idempotent-incremental-ingestion.md) Idempotent, incremental ingestion with Qdrant as the only durable store
- [0005](docs/adr/0005-in-process-tracing-not-opentelemetry.md) In-process trace spans and Prometheus, not OpenTelemetry yet
- [0006](docs/adr/0006-untrusted-tool-output.md) Treat agent tool output as untrusted data

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

## License

[MIT](LICENSE)
