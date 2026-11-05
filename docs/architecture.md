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

New chunks are embedded and upserted in batches of about 256 points (`pipeline.UPSERT_BATCH`), never splitting one file across two batches. A point averages about 8.9 KB of JSON on this repo, so the old single upsert per ingest would pass Qdrant's 32 MB default request limit at roughly 3,800 chunks. Keeping each file in one batch means an ingest that dies part-way leaves every file either fully written or absent, so the next ingest repairs it.

The indexed repository is not trusted, so neither ingest nor the file tools follow a symlink out of it. `iter_source_files` skips a file whose real path is outside the repo (a link's own name picks the extension, so `notes.md -> ~/.ssh/id_rsa` would otherwise be indexed), and `expand_context`/`get_file` resolve symlinks before checking that the path stays under the repo root (`context_expand.resolve_inside`). Links that stay inside the repo still work.

Qdrant is the only durable store. The BM25 index and the repo root used by `expand_context`/`get_file` are rebuilt from Qdrant payloads on first use after a restart, or after an ingest that went through another replica (`pipeline.restore`, see "Replicas and state"). Before this, a restarted retrieval-service, or the second of the two k8s replicas, had no lexical index and could not read files until someone re-ingested.

## Agent layer: bounded tool-calling loop

`POST /agent` (`app/routers/agent.py`, loop in `app/agent/loop.py`) is a small native loop, not a call into an agent framework. For three tools and a four-step cap, a graph-orchestration framework's state machine is overhead the system does not need, and it would make the core system depend on an external framework it does not otherwise require.

- State (`app/agent/state.py`): `AgentState` holds only this task's progress, the messages sent to the LLM, tool calls made (with each result as the model saw it, after sanitizing), step count, final answer, citation verdicts, and injection flags. It is separate from conversation history (owned per session by the caller) and from retrieved context (ephemeral, lives only inside a tool result).
- Tools (`app/agent/tools.py`): `search_code` (wraps the context-layer pipeline above), `expand_context`, `get_file`. Each has a Pydantic argument schema validated before the call reaches gRPC. A failed tool call returns text to the model ("Tool X failed: ...") instead of crashing the request.
- Bounds: `MAX_STEPS=4`, `MAX_TOOL_CALLS=6`, `TIMEOUT_S=60`. The timeout is an `asyncio.timeout` around the whole run, so it also cancels an LLM or tool call that is still in flight; an earlier version only checked the clock between steps, which let a hung backend hold a request for minutes. Hitting any bound ends the loop with an explicit "I couldn't gather enough information" answer, not a silent truncation or an infinite loop.
- Tool execution: the tool calls a model emits in one step run concurrently (`asyncio.gather`), since they are independent read-only lookups. Every `tool_call` id gets a `tool` message back, including calls dropped because the tool budget ran out. OpenAI-compatible servers reject a transcript with an unanswered tool call.
- Untrusted tool output (`app/agent/untrusted.py`, `docs/adr/0006-untrusted-tool-output.md`): tool results come from whoever wrote the indexed repository, so the loop treats them as data. Before a result reaches the model, sentences that read like instructions to it (override earlier instructions, "you are now ...", system-prompt requests, notes addressed to an AI, "do not flag/report this", "mark this as safe", chat-template tokens) are replaced with `[removed: instruction-like text]` by regex rules, keeping line numbers aligned. The rest is wrapped in `<<untrusted tool_output id=...>>` delimiters with a fresh random id per result, and the system prompt says everything inside them is data, never instructions. Each removal is recorded on `AgentState.injection_flags` (rule, removed text, file and line), returned as `injection_flags` in the response, and counted by `agent_injection_flags_total{rule}`. The regex is a first line of defence, not a complete one: `eval/agent_eval.py` measures it catching 18 of 23 hand-written injections and flagging 2 of 20 benign sentences, and the ADR lists what it misses.
- Citation grounding (`app/agent/citations.py`): every `[path:start-end]` citation in the final answer is checked against what the tools actually returned in that run (an overlapping `search_code` hit, an `expand_context` window, or a `get_file` read; for a read truncated at the 20 KB cap, only the lines before the cut, which `get_file` now states in its truncation notice). Lines the injection guard removed do not count as evidence, so a citation that lands only on injected text is ungrounded. The response carries `citations.grounded` and `citations.ungrounded`, and `agent_citations_total{grounded}` counts both, so a model that cites code it was never shown is visible per response and in aggregate.
- Identifier support (`citations.unsupported_identifiers`): a grounded range does not prove the answer describes it correctly, so code identifiers in the same sentence as a citation (backticked names, `name()`, snake_case and SCREAMING_SNAKE names, `class X`/`def x`, file paths, quoted string literals) must appear in the text the tools returned for the cited range, plus two lines of slack and the enclosing `def`/`class` line. Ones that do not are returned as `citations.unsupported_identifiers` and counted by `agent_unsupported_identifiers_total`. It is checked against the sanitized text, so a name that only appeared in removed text is unsupported. Like the grounding check, it is regex, interval, and substring matching, not an LLM judge; it can miss a wrong claim about a name that is present, and it skips backticked expressions rather than guessing which name they mean.
- Audit log (`app/agent/audit.py`): with `GATEWAY_AGENT_AUDIT_LOG` set to a file path (empty, the default, disables it), each run appends one JSON line: timestamp, SHA-256 of the task (not the task text), model, steps, stop reason, every tool call with its arguments, grounded/ungrounded citations, unsupported identifiers, injection flags, and duration. A run that raises (backend down, client gone) is still logged, with `stopped_reason: "error"`. Writes go through a thread so the event loop is not blocked, and a failed write is logged and counted (`agent_audit_write_failures_total`) instead of failing the request. Tool arguments are stored verbatim and can echo the question, so treat the file as sensitive. The write lock is per process, so give each replica its own file (pod-local storage or a per-pod path), not one shared file.
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

`gateway-api` exposes two health endpoints on purpose. `/livez` checks only that the process itself is alive. `/healthz` aggregates the LLM backend and retrieval-service, and answers 503 with the same body (`"ready": false`) when either is down. Kubernetes' `httpGet` probe only looks at the status code, and this endpoint used to return 200 either way, so the readiness probe never took a pod out of rotation. Liveness probes point at `/livez` and readiness probes at `/healthz`, otherwise a slow-to-load model or a restarting retrieval-service would cause Kubernetes to kill and restart an otherwise fine gateway pod. Compose mirrors the same idea: `gateway-api` has a soft dependency on the LLM backend, it starts and answers `/healthz` honestly even before Ollama, vLLM, or llama.cpp is ready, rather than blocking the whole stack's boot on it.

## Auth

JWT, issued by `POST /token` against demo credentials. Swap for a real user store before this handles real users. At startup the gateway logs a warning for each setting still at its shipped value (`GATEWAY_JWT_SECRET`, and the `admin`/`admin` demo login), since anyone who reads this repo knows them. Requests are size-bounded before anything is sent downstream: a question or agent task over `GATEWAY_MAX_QUESTION_CHARS` (16,000 by default) or a `top_k` outside 1-50 is rejected with 422 (an error frame on the WebSocket). REST calls send it as a Bearer header; the WebSocket sends it as a `?token=` query parameter, since browser WebSocket clients cannot set custom headers on the handshake. The token is checked again on every message, so a long-lived socket is closed (1008) once its token expires instead of staying authorized. A malformed frame (not JSON, not an object, no non-empty `question`) gets an `error` frame back and the socket stays open; it used to raise and drop the connection.

## Observability

`gateway-api` exposes Prometheus metrics via `prometheus-fastapi-instrumentator` (`/metrics`), plus agent-specific metrics in `app/metrics.py`: `agent_steps_total` (a histogram of round-trips per run), `agent_tool_calls_total` (labeled by tool; a tool name the model invents is counted as `unknown`, so model output cannot create new series), `agent_stopped_reason_total` (labeled done, max_steps, or timeout), `agent_citations_total` (labeled by whether a tool result backs the citation), `agent_unsupported_identifiers_total`, `agent_injection_flags_total` (labeled by rule), and `agent_audit_write_failures_total`. The Grafana dashboard plots injection flags by rule and unsupported identifiers next to the ungrounded-citation fraction. `retrieval-service` exposes its own counters and histograms (search, ingest, and rerank requests, search latency, `retrieval_ingest_chunks_embedded_total` for how much embedding work ingests actually do) on a separate metrics port. Both are scraped by Prometheus and shown in a provisioned Grafana dashboard (`monitoring/grafana/dashboards/api-overview.json`). `/healthz` aggregates liveness of the LLM backend and retrieval-service for use as a readiness probe.

Tracing is deliberately not OpenTelemetry or Jaeger yet (`docs/adr/0005-in-process-tracing-not-opentelemetry.md`). There is one consumer of trace data (the debug trace and the eval harness), and the OpenTelemetry GenAI conventions are still marked Development. The in-process `Trace` object in `retrieval-service/tracing.py` answers "what happened and how long did it take" per request; Prometheus answers "how often" in aggregate. If this runs with several teams debugging across services, that calculation changes.

The gateway's gRPC client keeps one channel per process with keepalive and retries `UNAVAILABLE` up to 3 attempts with backoff (`app/rag_client.py`, `docs/adr/0001-grpc-between-gateway-and-retrieval.md`). That is only safe because every RPC is idempotent. The LLM client has a 120 s read timeout between streamed chunks; it previously had no timeout at all on the streaming path.

## Replicas and state

`gateway-api` holds no state across requests. `AgentState` lives for one `/agent` call, and neither `/chat` nor the WebSocket keeps conversation history, so `k8s/gateway-api.yaml`'s `replicas: 2` is safe. The flip side is that there is no multi-turn memory: each question is answered on its own. The optional agent audit log is append-only output, not state a request reads back, so it does not change this.

`retrieval-service` also runs two replicas. Its durable state is in Qdrant; the in-memory BM25 index is rebuilt from Qdrant when it is missing or stale (see "Ingestion"). Every ingest stamps the collection with a new generation id in a one-point companion collection (`<collection>__ingest_meta`), and `pipeline.restore` compares it with the generation the replica's index was built from, so a replica picks up an ingest that went through the other replica on its next lexical or hybrid search, `expand_context`, or `get_file`, at the cost of one point lookup per call. This used to need a restart. Dense-only search, the default, no longer builds the lexical index at all.

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
