# Architecture

CodeSage has three layers: a context/retrieval pipeline, an agent loop built on top of it, and the infrastructure that runs both. This document covers each in turn.

```
                         +---------------------------------------------+
                         |              Cloud VM (public)               |
                         |                                               |
   client -- HTTP/WS --> |  Traefik --> gateway-api (FastAPI)            |
                         |   (gateway,      |  REST /chat                |
                         |    rate limit,   |  POST /agent (bounded      |
                         |    routing)      |    tool-calling loop)      |
                         |                  |  WS   /ws/chat             |
                         |                  |  JWT auth (/token)         |
                         |                  |  /metrics, /healthz        |
                         |                  |        |                   |
                         |  Prometheus <-- scrape    | gRPC              |
                         |  Grafana   <-- dashboards v                   |
                         +------------------+----------------------------+
                                            | Search / IngestRepo /
                                            | ExpandContext / GetFile
                                            v
                         +---------------------------------------------+
                         |           Edge / GPU node (optional)         |
                         |                                               |
                         |  retrieval-service (gRPC)                    |
                         |    query classifier -> dense (Qdrant) +      |
                         |    lexical (bm25s) -> fusion -> optional     |
                         |    rerank -> token-budgeted assembly         |
                         |        |                                     |
                         |        v                                    |
                         |      Qdrant (vector store)                   |
                         |                                               |
                         |  Ollama / vLLM / llama.cpp (local LLM)       |
                         |    one OpenAI-compatible client either way   |
                         +---------------------------------------------+
```

## Why split cloud and edge

`gateway-api` is stateless, cheap, and public-facing. It belongs on a small always-on cloud VM. `retrieval-service`, Qdrant, and the LLM backend need CPU/GPU and disk for models and vectors. They can live on a separate machine, a GPU workstation, a spot instance, an on-prem box, that never needs a public IP, only a private link back to the cloud VM. The gateway talks to them over gRPC and HTTP, so the split is an environment variable change (`GATEWAY_RETRIEVAL_GRPC_TARGET`, `GATEWAY_LLM_BASE_URL`), not a code change. See `services/edge-inference/README.md`.

Everything also runs as a single `docker-compose up` on one machine for local development; the split is optional.

## Request paths

- `POST /chat`: retrieve chunks via gRPC, build a prompt, call the LLM, return `{answer, sources}` in one response.
- `WS /ws/chat`: the same retrieval step, but the answer streams token by token.
- `POST /agent`: a bounded, multi-step tool-calling loop instead of a single retrieve-then-answer pass. See "Agent layer" below.
- gRPC to `retrieval-service`: internal only, never exposed publicly. A typed contract (`proto/retrieval.proto`) over a low-latency internal boundary.

## Context layer: retrieval, ranking, evaluation

`retrieval-service`'s `Search` RPC runs a pipeline, not a single vector lookup. The pipeline itself is `pipeline.py` (`search` and `ingest`), independent of gRPC; `server.py` only converts protos and records metrics, which is what lets the pipeline be tested against an embedded Qdrant with no server. Everything below lives in `services/retrieval-service/`.

1. `query_classifier.py`: a handful of regexes decide, without an LLM call, how much a query looks like it wants an exact identifier match (snake_case, camelCase, CONSTANT_CASE, dotted paths, quoted strings) versus a semantic match. Used when hybrid mode is requested; see the note on the default strategy below.
2. Dense search (`vector_store.py`, Qdrant) is the default. Lexical search (`bm25_index.py`, bm25s) also runs when `strategy="hybrid"` is requested, and the two are combined in `fusion.py` via weighted reciprocal rank fusion using the classifier's output as the weight.
3. `fusion.py` also dedupes chunks whose line ranges overlap on the same file, and assembles a token-budgeted context that never truncates a single chunk, regardless of which strategy produced the candidates.
4. `reranker.py`: an optional cross-encoder pass, off by default. `eval/ablation.py` measured it improving Recall@5 by 0.10 on this corpus at roughly 25x the latency; see `docs/evaluation.md` for the numbers and when that trade is worth making.

**Default strategy is dense-only, not hybrid.** `eval/ablation.py` measured hybrid fusion tying dense-only on Recall@5 and losing on MRR on this corpus (see `docs/evaluation.md` and `docs/adr/0002-dense-retrieval-by-default.md`), so `pipeline.py` and `rag_client.py` both default `strategy` to `"dense"`. Hybrid and lexical-only stay available via the `strategy` field on `SearchRequest` for corpora where they measure better; this default is a data-driven choice, not an assumption, and should be re-checked if the corpus changes significantly.
5. `context_expand.py`: given a retrieved chunk, fetch more surrounding lines from the same file. A chunk already carries its file and line range, which is enough to recover more context without tracking a repo/module/class hierarchy separately.
6. `chunking_python.py`: Python files are chunked on `def`/`class` boundaries using the stdlib `ast` module rather than fixed-size line windows, so a chunk is usually a whole function. Falls back to a line-window chunker (`chunking.py`) for non-Python files, syntax errors, or any single unit too large to embed whole.
7. `tracing.py`: every stage records a timed span. `Search` returns the full trace, so a bad answer's cause (wrong classification, dense search missed it, fusion ranked it too low) can be inspected rather than guessed.

`eval/` measures whether each of these choices actually helps on this corpus and by how much. See `docs/evaluation.md`.

### Ingestion

`IngestRepo` is idempotent and incremental (`pipeline.ingest`, `docs/adr/0004-idempotent-incremental-ingestion.md`). Each chunk's Qdrant payload records the SHA-256 of its file, and point IDs are derived from (collection, path, line range, file hash). A re-ingest skips files whose hash is unchanged, deletes and re-embeds changed files, and deletes chunks of files that no longer exist. On this repo (105 files, 353 chunks, `scripts/bench_ingest.py`) an unchanged re-ingest embeds 0 chunks, and editing one file re-embeds only that file's chunks (3 for README.md). Before this, every ingest re-embedded everything under fresh random IDs, so a second ingest doubled the collection.

Qdrant is the only durable store. The BM25 index and the repo root used by `expand_context`/`get_file` are rebuilt from Qdrant payloads on first use after a restart (`pipeline.restore`). Before this, a restarted retrieval-service, or the second of the two k8s replicas, had no lexical index and could not read files until someone re-ingested.

## Agent layer: bounded tool-calling loop

`POST /agent` (`app/routers/agent.py`, loop in `app/agent/loop.py`) is a small native loop, not a call into an agent framework. For three tools and a four-step cap, a graph-orchestration framework's state machine is overhead the system does not need, and it would make the core system depend on an external framework it does not otherwise require.

- State (`app/agent/state.py`): `AgentState` holds only this task's progress, the messages sent to the LLM, tool calls made, step count, final answer. It is separate from conversation history (owned per session by the caller) and from retrieved context (ephemeral, lives only inside a tool result).
- Tools (`app/agent/tools.py`): `search_code` (wraps the context-layer pipeline above), `expand_context`, `get_file`. Each has a Pydantic argument schema validated before the call reaches gRPC. A failed tool call returns text to the model ("Tool X failed: ...") instead of crashing the request.
- Bounds: `MAX_STEPS=4`, `MAX_TOOL_CALLS=6`, `TIMEOUT_S=60`. The timeout is an `asyncio.timeout` around the whole run, so it also cancels an LLM or tool call that is still in flight; an earlier version only checked the clock between steps, which let a hung backend hold a request for minutes. Hitting any bound ends the loop with an explicit "I couldn't gather enough information" answer, not a silent truncation or an infinite loop.
- Tool execution: the tool calls a model emits in one step run concurrently (`asyncio.gather`), since they are independent read-only lookups. Every `tool_call` id gets a `tool` message back, including calls dropped because the tool budget ran out. OpenAI-compatible servers reject a transcript with an unanswered tool call.
- Citation grounding (`app/agent/citations.py`): every `[path:start-end]` citation in the final answer is checked against what the tools actually returned in that run (an overlapping `search_code` hit, an `expand_context` window, or a `get_file` read). The response carries `citations.grounded` and `citations.ungrounded`, and `agent_citations_total{grounded}` counts both, so a model that cites code it was never shown is visible per response and in aggregate. It is a regex and interval check, not an LLM judge.
- Model routing (`app/agent/model_router.py`): an optional fast/capable model split behind one heuristic function based on question length and whether it looks like a multi-part question. With no fast model configured, the default, every task uses `GATEWAY_LLM_MODEL`.
- Tool-calling protocol: `app/llm_client.py`'s `complete_with_tools` sends OpenAI-style `tools=[...]` and parses `tool_calls` out of the response. It is the same client `/chat` uses, extended rather than duplicated.

### MCP adapter

`services/gateway-api/app/mcp/server.py` exposes `search_code` and `expand_context` as MCP tools over stdio, for external MCP clients to reuse CodeSage's retrieval without reimplementing the gRPC client. It wraps `app.rag_client` directly. The gateway's own `/agent` loop does not route through it; there is no benefit to adding a subprocess hop to the gateway's own request path.

The `mcp` package pulls a newer `starlette` than the one FastAPI is pinned to, and installing both in the same environment breaks FastAPI. Because of that, this adapter has its own `requirements.txt` under `app/mcp/` and is meant to run in its own environment, not inside the main `gateway-api` container.

## LLM backends

`app/llm_client.py` speaks the OpenAI-compatible `/v1/chat/completions` API rather than any one server's native API. Ollama, vLLM, and llama.cpp's `llama-server` all implement it, so the client code is the same across all three. Switching backends is `GATEWAY_LLM_BASE_URL` and `GATEWAY_LLM_MODEL`, not a code change.

Being OpenAI-compatible for plain chat completions does not automatically mean a backend supports `tools=[...]`. Each needs its own configuration:

| Backend | Bring it up | Tool-calling status |
|---|---|---|
| Ollama (default) | `make up` | Verified end-to-end against `ollama/ollama:0.3.12` with a small model (`qwen2.5:0.5b`): a raw `tools=[...]` request returns proper `tool_calls`, and the full `/agent` endpoint (auth, loop, LLM call) was exercised live with a correct structured response. |
| vLLM | `make up-vllm` (`docker-compose.vllm.yml`) | Configured (`--enable-auto-tool-choice --tool-call-parser hermes`, default model switched to `Qwen/Qwen2.5-7B-Instruct-AWQ`, since the earlier Mistral v0.2 pick predates reliable tool-calling) but not live-tested; pulling the model and image needs more disk than was available while building this. |
| llama.cpp (`llama-server`) | `make up-llamacpp` (`docker-compose.llamacpp.yml`) | Configured (`--jinja`, required for llama-server to render tool-call templates at all, plus a Qwen2.5/Hermes-family GGUF) but not live-tested, for the same reason. |

One finding from the live Ollama test is worth recording: the tool-calling protocol works, but a 0.5B model does not reliably use it. On some prompts it ignored the system prompt's tool-use instruction and answered directly; on others it wrote out a fake function call as plain text instead of emitting a proper `tool_calls` response. That is a model-capability limit, not a protocol or code issue, and it is why the documented default for actual agent use is a larger, tool-tuned model (`llama3.1:8b-instruct-q4_0`). The 0.5B model was only used to verify the mechanism cheaply.

## Quantization

Ollama serves a quantized model (`llama3.1:8b-instruct-q4_0` by default) so the stack runs on a CPU-only cloud VM or a modest GPU; `q4_0` is a 4-bit-per-weight GGUF quantization chosen by Ollama's model registry. For llama.cpp, that step is explicit: `scripts/quantize_gguf.sh` runs llama.cpp's own `llama-quantize` tool against an f16/f32 GGUF to produce a smaller quant such as `Q4_K_M`. For vLLM, the equivalent is picking an AWQ or GPTQ-quantized model from the Hub (`docker-compose.vllm.yml` defaults to one). The embedding model in `retrieval-service` runs on CPU by default and switches to CUDA via `EMBEDDING_DEVICE=cuda` (see `docker-compose.gpu.yml`).

`retrieval-service`'s Dockerfile takes a `TORCH_VARIANT` build arg, `cpu` by default or `cuda`, that picks between the CPU-only PyTorch wheel index and the default CUDA-enabled one. The CPU build alone saves close to a gigabyte of unused NVIDIA package downloads, so the default local and CI build stays fast and the image stays small. `docker-compose.gpu.yml` and `services/edge-inference/docker-compose.edge.yml` are the only places that set `TORCH_VARIANT=cuda`.

## Liveness vs. readiness

`gateway-api` exposes two health endpoints on purpose. `/livez` checks only that the process itself is alive. `/healthz` aggregates the LLM backend and retrieval-service. Liveness probes point at `/livez` and readiness probes at `/healthz`, otherwise a slow-to-load model or a restarting retrieval-service would cause Kubernetes to kill and restart an otherwise fine gateway pod. Compose mirrors the same idea: `gateway-api` has a soft dependency on the LLM backend, it starts and answers `/healthz` honestly even before Ollama, vLLM, or llama.cpp is ready, rather than blocking the whole stack's boot on it.

## Auth

JWT, issued by `POST /token` against demo credentials. Swap for a real user store before this handles real users. REST calls send it as a Bearer header; the WebSocket sends it as a `?token=` query parameter, since browser WebSocket clients cannot set custom headers on the handshake.

## Observability

`gateway-api` exposes Prometheus metrics via `prometheus-fastapi-instrumentator` (`/metrics`), plus agent-specific metrics in `app/metrics.py`: `agent_steps_total` (a histogram of round-trips per run), `agent_tool_calls_total` (labeled by tool), `agent_stopped_reason_total` (labeled done, max_steps, or timeout), `agent_citations_total` (labeled by whether a tool result backs the citation). `retrieval-service` exposes its own counters and histograms (search, ingest, and rerank requests, search latency, `retrieval_ingest_chunks_embedded_total` for how much embedding work ingests actually do) on a separate metrics port. Both are scraped by Prometheus and shown in a provisioned Grafana dashboard (`monitoring/grafana/dashboards/api-overview.json`). `/healthz` aggregates liveness of the LLM backend and retrieval-service for use as a readiness probe.

Tracing is deliberately not OpenTelemetry or Jaeger yet (`docs/adr/0005-in-process-tracing-not-opentelemetry.md`). There is one consumer of trace data (the debug trace and the eval harness), and the OpenTelemetry GenAI conventions are still marked Development. The in-process `Trace` object in `retrieval-service/tracing.py` answers "what happened and how long did it take" per request; Prometheus answers "how often" in aggregate. If this runs with several teams debugging across services, that calculation changes.

The gateway's gRPC client keeps one channel per process with keepalive and retries `UNAVAILABLE` up to 3 attempts with backoff (`app/rag_client.py`, `docs/adr/0001-grpc-between-gateway-and-retrieval.md`). That is only safe because every RPC is idempotent. The LLM client has a 120 s read timeout between streamed chunks; it previously had no timeout at all on the streaming path.

## Replicas and state

`gateway-api` holds no state across requests. `AgentState` lives for one `/agent` call, and neither `/chat` nor the WebSocket keeps conversation history, so `k8s/gateway-api.yaml`'s `replicas: 2` is safe. The flip side is that there is no multi-turn memory: each question is answered on its own.

`retrieval-service` also runs two replicas. Its durable state is in Qdrant; the in-memory BM25 index is rebuilt from Qdrant on first use (see "Ingestion"). One gap remains: a replica that has already built its BM25 index does not see a later ingest that went through the other replica until it restarts. This only affects the non-default `hybrid` and `lexical` strategies.

## Other decisions and why

A few components that might be expected here were left out, on purpose:

- **An agent framework (LangGraph or similar).** Three tools and a four-step bounded loop do not need a graph-orchestration framework's state machine. A plain Python loop (`app/agent/loop.py`) covers it in about 80 lines and keeps the system usable without an external agent-framework dependency.
- **A separate reranker service.** The reranker is one model, one function, called from one place. A new service boundary needs a real reason, independent scaling, runtime isolation, a separate deployment lifecycle, and none applies yet. It runs in-process in `retrieval-service`, lazy-loaded (`reranker.py`).
- **A dedicated query-decomposition stage.** Breaking a complex question into sub-questions is exactly what the agent's iterative `search_code` calls already do. A separate decomposition module would duplicate that. This means decomposition only happens in `/agent` mode, not in the single-shot `/chat` path, which is an explicit scope boundary.
- **PDF or web ingestion.** The corpus this system actually serves is source code and Markdown docs. `chunking.py`'s `TEXT_EXTENSIONS` stays scoped to that; parsers for formats nothing here produces would be unused code.
- **Redis or another shared cache.** The gateway is stateless and the retrieval-service rebuilds its in-memory index from Qdrant, so there is no state that needs a second store.
- **A torch-free embedding runtime (ONNX via fastembed).** Likely a large cut in image size and cold start, and it supports the same MiniLM model and cross-encoder. Not done in this pass because it has to be measured against the current sentence-transformers path (same questions, same corpus) before switching, and there was not enough free disk to hold both runtimes for that comparison.

## Resource management

Every container and pod declares CPU and memory requests and limits (`deploy.resources` in `docker-compose.yml`, `resources.requests`/`limits` in `k8s/*.yaml`), sized to what each service actually needs. The embedding model and gRPC worker pool in `retrieval-service` get the most headroom; Traefik and Grafana get the least. `ollama`'s GPU reservation (`nvidia.com/gpu` in Kubernetes, `deploy.resources.reservations.devices` in Compose) is isolated to its own override files, so the base stack runs CPU-only by default.
