# Improvements log

Each round audits the codebase, makes 2-4 targeted improvements, verifies them, and records what changed here. Every claim below was checked by running the code; anything not verified says so.

## Round 1: symlink escape, truncated-read grounding, streaming robustness

Branch `improve/round-1`, stacked on `reliability-layer` (athish-shubhan/CodeSage#1).

### 1. Symlinks could read and index files outside the repo (security)

**Found:** the indexed repository is untrusted (ADR 0006), but `chunking.iter_source_files` read any file whose *name* had a text extension, and `context_expand.expand`/`read_file` checked containment with `os.path.normpath`, which does not resolve symlinks. Reproduced with a repo containing `leak.md -> ../outside/secret.txt` and `linkdir -> ../outside`: ingest scanned `leak.md`, and `get_file("leak.md")`, `get_file("linkdir/secret.txt")` and `expand_context("leak.md", ...)` all returned the secret.

**Changed:** `iter_source_files` skips files whose real path is outside the repo; `expand`/`read_file` go through a new `resolve_inside(root, rel)` that resolves symlinks on both sides before the containment check. Links that stay inside the repo, and a repo root that is itself a symlink, still work.

**Verified:** 3 new retrieval-service tests and 1 new integration test (ingest over real gRPC, then `search`, `get_file`, `expand_context`); the integration test fails with the fix reverted and passes with it.

### 2. A truncated `get_file` grounded citations to lines the model never saw

**Found:** `get_file` caps reads at 20 KB, but `citations.check` treated any successful read as evidence for the whole file. Reproduced with a 5,000-line file: the model was shown lines 1-1307, and `[big.py:4000-4001]` was reported grounded.

**Changed:** a truncated read now ends with `... (truncated after line N; use expand_context to read further)`, which also tells the model where to continue, and the citation check grounds only lines 1-N for it. An untruncated read still grounds the whole file, as before.

**Verified:** new tests in `test_citations.py` and `test_tools.py`; the agent eval gate is unchanged (36/36 label checks, detector 0.90 / 0.78).

### 3. Streaming paths crashed on input they should tolerate

**Found:** in `/ws/chat`, one frame that was not a JSON object (`not json`, `[1, 2]`) raised out of the handler and dropped the connection (reproduced: `JSONDecodeError`). The handshake token was never checked again, so a socket stayed authorized after the token expired. In `stream_chat`, a chunk with `"choices": []`, the shape of an OpenAI-style usage chunk, would raise `IndexError` mid-answer. Not observed against a live backend here (none available); the chunk shape is what OpenAI-compatible servers send with `stream_options.include_usage`.

**Changed:** a bad frame (not JSON, not an object, missing or blank `question`) gets an `error` frame and the socket stays usable; the token is re-checked on every message and an expired one closes the socket with 1008; empty `choices` chunks are skipped.

**Verified:** 3 new tests, each failing on the old code and passing on the new.

### Results

| Suite | Before (reliability-layer) | After |
|---|---|---|
| gateway-api | 79 | 85 passed |
| retrieval-service | 51 | 54 passed |
| integration | 4 | 5 passed |
| eval | 29 | 29 passed |
| agent eval gate | passed | passed (unchanged numbers) |
| ruff 0.14.0 | clean | clean |

### Not done

- The `retrieval-smoke` job (real embedder) cannot run in this environment; CI runs it.
- A symlink's target is only checked at ingest and read time; a link that is retargeted between the two is checked again at read time, but an already-indexed chunk keeps its old content until the next ingest.

## Round 2: batched ingest, request bounds and insecure-default warnings, bounded metric labels

Branch `improve/round-2`, stacked on `improve/round-1` (athish-shubhan/CodeSage#2).

### 1. Ingest sent every new chunk to Qdrant in one request

**Found:** `pipeline.ingest` embedded all new chunks at once and upserted them in a single request. Measured on this repo's own chunks (504 chunks from 116 files, with 384-d vectors as all-MiniLM-L6-v2 produces): a point averages 8,862 bytes of JSON, so the whole ingest was one 4.5 MB request, and Qdrant's default 32 MB request limit (`service.max_request_size_mb`) would be passed at about 3,800 chunks, roughly 870 files at this repo's density. Not reproduced against a Qdrant server here (none available); the limit is Qdrant's documented default.

**Changed:** chunks are embedded and upserted in batches of about 256 points (~2.3 MB), never splitting a file across batches. That last part matters: with naive slicing, an ingest that dies between batches leaves a file half-written but already carrying its new hash, so the next ingest thinks it is unchanged and never writes the missing chunks.

**Verified:** 3 new tests against embedded Qdrant: batch sizes and file-to-batch assignment, an oversized single file staying in one batch, and an ingest that crashes on its second batch being fully repaired by the next one. The two ingest tests fail against a naive slicing batcher and pass with the file-aligned one.

### 2. Unbounded request sizes; shipped secrets used silently

**Found:** `/chat`, `/agent`, and `/ws/chat` accepted a question or task of any length and passed it to retrieval and the LLM, and `top_k` was unbounded (retrieval only fetches 20 candidates per strategy, so more never helps). The gateway also started without comment with the default `GATEWAY_JWT_SECRET` (which lets anyone who reads the repo sign valid tokens) and the `admin`/`admin` demo login.

**Changed:** questions and tasks over `GATEWAY_MAX_QUESTION_CHARS` (16,000 characters by default, about 4,000 tokens) and `top_k` outside 1-50 are rejected with 422 before any downstream call; the WebSocket answers with an error frame and stays open. At startup the gateway logs one warning per setting still at its shipped value. Defaults are unchanged: nothing is refused, only reported.

**Verified:** 8 new tests (oversized question, `top_k` 0 and 51, a question exactly at the limit accepted, oversized agent task, oversized WebSocket question, warnings reported and cleared, startup logging); each rejected case asserts no downstream call was made.

### 3. Model output controlled a Prometheus label; malformed tool arguments got a misleading error

**Found:** `agent_tool_calls_total{tool}` used the tool name from the model's reply as its label. Reproduced: one run with five invented tool names created five new series. A model that hallucinates names, or is steered by injected text, can grow the series count without bound. Separately, tool arguments that were not valid JSON were silently replaced with `{}`, so the model was told `query: field required` about arguments it did send.

**Changed:** names outside the three real tools are counted as `unknown`. Arguments that are not a JSON object get `Invalid arguments for <tool>: arguments must be a JSON object.` and the tool is not called.

**Verified:** 2 new tests.

### Results

| Suite | Before (round 1) | After |
|---|---|---|
| gateway-api | 85 | 95 passed |
| retrieval-service | 54 | 57 passed |
| integration | 5 | 5 passed |
| eval | 29 | 29 passed |
| agent eval gate | passed | passed (36/36, detector 0.90 / 0.78, unchanged) |
| ruff 0.14.0 | clean | clean |

### Not done

- The 32 MB limit and the batch size were not exercised against a real Qdrant server here; CI's `retrieval-smoke` job uses one but only ingests 4 files.
- Request limits are per request, not per user; there is still no rate limiting in the gateway (Traefik is the documented place for it).

## Round 3: readiness that gates traffic, replica-fresh lexical index, ingest path allowlist

Branch `improve/round-3`, stacked on `improve/round-2` (athish-shubhan/CodeSage#3).

### 1. `/healthz` returned 200 with its dependencies down

**Found:** the k8s readiness probe is an `httpGet` on `/healthz`, which only looks at the status code, but `/healthz` returned 200 whatever the LLM backend and retrieval-service reported. Reproduced: with both mocked down it answered 200 with `"llm_status": "unreachable"` in the body. The readiness probe could never take a pod out of rotation.

**Changed:** 503 with the same body (plus `"ready": false`) when either dependency is down. `/livez` is unchanged. `scripts/smoke_test.sh` uses `--fail-with-body` so a 503 still prints which dependency is down.

**Verified:** 5 new tests (all four up/down combinations, and `/livez` staying 200).

### 2. A retrieval replica kept a stale lexical index after another replica's ingest

**Found:** the documented gap in "Replicas and state": the BM25 index lives in each replica's memory and was only rebuilt when missing. Reproduced by giving a second "replica" the first one's in-memory state after another ingest: lexical search missed a newly added file and still returned chunks of a deleted one. Separately, every dense search (the default) called `restore`, which builds the lexical index after a restart although dense search never reads it.

**Changed:** each ingest writes a fresh generation id to a one-point companion collection (`<collection>__ingest_meta`); `restore` rebuilds when the stored generation differs from the one the replica's index was built from. Cost: one point lookup per lexical or hybrid search, `expand_context`, and `get_file`. Dense-only search no longer calls `restore`. Collections ingested before this change have no generation and are rebuilt once, not on every call.

**Verified:** 5 new tests against embedded Qdrant: the added-file and deleted-file cases (both failed before the change), dense search not building the index (also failed before), a never-ingested collection, and a pre-generation collection rebuilding exactly once over three searches.

### 3. `IngestRepo` accepted any path on the retrieval host

**Found:** an authenticated `/ingest` call could index any directory the retrieval-service can read; search and `get_file` then serve its files. On this machine `repo_path="/etc"` would index 27 files (config TOML, JSON policies, shell profiles). The gateway also reported every gRPC error as 503 "retrieval-service unavailable", including a refused or mistyped `repo_path`.

**Changed:** `INGEST_ALLOWED_ROOTS` (`:`-separated) limits ingest to those directories, checked on the real path so `..` and symlinks cannot climb out, and checked before existence so a refusal does not reveal whether a path exists. Unset keeps the old behaviour; `docker-compose.yml`, the edge compose file, and `k8s/retrieval-service.yaml` set it to `/data`, where repos are mounted (`make ingest-self` uses `/data/codesage-agent`). The gateway maps `INVALID_ARGUMENT` to 400.

**Verified:** 3 new retrieval-service tests (outside root, nonexistent path refused rather than "not a directory", `..` escape, symlink into the root judged by its target, unset env unchanged) and 1 gateway test for the 400. Compose and k8s files still parse.

### Results

| Suite | Before (round 2) | After |
|---|---|---|
| gateway-api | 95 | 101 passed |
| retrieval-service | 57 | 65 passed |
| integration | 5 | 5 passed |
| eval | 29 | 29 passed |
| agent eval gate | passed | passed (36/36, detector 0.90 / 0.78, unchanged) |
| ruff 0.14.0 | clean | clean |

### Not done

- The compose and k8s changes were validated as YAML only; there is no Docker daemon in this environment to bring the stack up. `make ingest-self` uses `/data/codesage-agent`, inside the new allowlist.
- Generation checks cover ingests through any replica, but not someone editing Qdrant by hand.
- The gateway still forwards gRPC and LLM error details to clients verbatim (internal hostnames can appear in them).

## Round 4: injection guard and citation checks on /chat, accurate chunk line numbers, no internal addresses in errors

Branch `improve/round-4`, stacked on `improve/round-3` (athish-shubhan/CodeSage#4).

### 1. `/chat` and `/ws/chat` had none of the untrusted-data handling `/agent` got

**Found:** the injection guard, delimiters, and citation checks were only wired into the agent loop, but `/chat` and `/ws/chat` put the same retrieved repository text into the prompt. Reproduced with the `payments.py` fixture chunk: the injected `AUDIT-OK-7731` sentence reached the LLM prompt, nothing delimited the context, and the response had no citation verdicts.

**Changed:** `app/chat_guard.py` runs `untrusted.sanitize` on each retrieved chunk before `build_prompt`, which now wraps the context in the same `<<untrusted ...>>` delimiters with a matching system-prompt rule. The answer is checked with the same `citations.check`/`unsupported_identifiers` against the sanitized chunks. `/chat` returns `citations` and `injection_flags` alongside the unchanged `sources`; on `/ws/chat` the `sources` frame carries `injection_flags` and the `done` frame `citations` (new keys only, no new frame types). New counters `chat_injection_flags_total{rule}` and `chat_citations_total{grounded}`.

**Verified:** 4 new tests: removals mapped to file lines 7 and 8, the canary absent from the prompt, a citation to the injected lines ungrounded, an invented identifier reported, the same over the WebSocket, and empty verdicts with no sources. Existing chat and WebSocket tests pass unchanged.

### 2. A chunk's `start_line` could name a blank line its text did not contain

**Found:** while checking that removals map to the right lines, `window_chunks` (and the Python chunker) stripped leading blank lines from a chunk's text but kept the window's first line as `start_line`. Every consumer, the citation check, injection-flag locations, and the model counting lines to cite, reads the text's first line as `start_line`. Measured on this repo: 4 of 543 chunks were off, each by one line (e.g. `docker-compose.vllm.yml:51`).

**Changed:** `chunking.trimmed_span` trims blank edge lines from the span as well as the text; the text is byte-identical to before. Existing indexes keep their old line numbers for unchanged files until those files are re-ingested (ingest skips unchanged hashes).

**Verified:** 2 new tests, including one that checks every line of every chunk of this repo against the file; both fail on the old chunker.

### 3. Error responses carried internal addresses

**Found:** reproduced with mocked failures: `/chat` returned `retrieval-service unavailable: ... ipv4:10.42.7.19:50051: Connection refused` and `LLM backend unavailable: Server error ... for url 'http://ollama.internal.svc:11434/v1/chat/completions'`; `/ws/chat` sent gRPC's whole debug string.

**Changed:** clients get the dependency and the category (`retrieval-service unavailable (UNAVAILABLE)`, `LLM backend unavailable (HTTP 500)`, `(timed out)`); the full error is logged at WARNING. Status codes are unchanged (503, 502, 400 for a refused `repo_path`, whose message is our own validation text and is still returned).

**Verified:** 3 new tests (REST gRPC, REST LLM, WebSocket), including that the address still reaches the server log.

### Results

| Suite | Before (round 3) | After |
|---|---|---|
| gateway-api | 101 | 108 passed |
| retrieval-service | 65 | 67 passed |
| integration | 5 | 5 passed |
| eval | 29 | 29 passed |
| agent eval gate | passed | passed (36/36, detector 0.90 / 0.78; false-positive corpus now 46 files, still 1 flag) |
| ruff 0.14.0 | clean | clean |

### Not done

- The `/chat` guard is not in `eval/agent_eval.py`'s cases; it is covered by gateway tests only.
- The MCP adapter (`app/mcp/server.py`) still returns raw retrieved text to MCP clients; it runs in its own environment and was not changed.

## Round 5: malformed LLM responses, /chat in the eval gate, a working MCP adapter

Branch `improve/round-5`, stacked on `improve/round-4` (athish-shubhan/CodeSage#5).

### 1. A 2xx response that was not a completion became an unhandled 500

**Found:** `complete_with_tools` indexed `resp.json()["choices"][0]["message"]` and `stream_chat` ran `json.loads` on every chunk, so a backend answering 200 with `{"choices": []}`, `{"error": "model not loaded"}`, or an HTML error page raised `IndexError`/`KeyError`/`JSONDecodeError`. The routers only map `httpx.HTTPError`, so all three reproduced as 500 on `/agent`. An `{"error": ...}` chunk mid-stream was silently skipped, which truncated the answer without saying so.

**Changed:** both paths raise `MalformedLLMResponse`, a subclass of `httpx.HTTPError`, so every existing handler maps it to 502 with `LLM backend unavailable (malformed response)` (the body goes to the server log).

**Verified:** 6 new tests (four bodies on `/agent`, two stream chunks on `/chat`); all six fail on the old code.

### 2. The `/chat` guard was not in the CI eval gate

**Found:** Round 4 added the injection guard and citation checks to `/chat` but left them out of `eval/agent_eval.py`, so the `agent-eval` gate only covered `/agent`.

**Changed:** cases can set `"path": "chat"`; they run the real `/chat` handler with fixture-backed retrieval and a scripted (replay) or real (live) LLM stream, and are scored the same way. Two cases added: the injected `payments.py` chunk, and an answer citing a file it was never shown.

**Verified:** replay now passes 45/45 label checks (was 36/36) across 11 cases; injection cases 4/4 stripped, flagged at the right lines, and uncitable. A new test shows the `/chat` case fails with sanitizing disabled. Replay answer rates moved because two scripted answers were added (grounded-citation rate 0.56 over 16 citations, unsupported-identifier rate 0.26 over 19 identifiers, abstention accuracy 0.91 over 11 cases); as before, those rates describe the scripts, not a model.

### 3. The MCP adapter could not start from its own requirements file

**Found:** `app/mcp/requirements.txt` lists `grpcio` but not `protobuf`, which the generated stubs import; in the main environment it only arrives through `grpcio-tools`. Reproduced in a fresh venv with exactly that file: `import app.mcp.server` failed with `ModuleNotFoundError: No module named 'google'`, on the unmodified adapter. Separately, the adapter returned raw repository text to the MCP client's model and passed `top_k` and `extra_lines` through unbounded.

**Changed:** `grpcio-tools==1.66.2` (the main service's pin, which brings protobuf and generates the stubs) added to the adapter's requirements, and the stub-generation step added to its run instructions. Results are sanitized and delimited like the agent's tool results; `top_k` is clamped to 1-15 and `extra_lines` to 1-200, the agent's own tool bounds. New CI job `mcp-adapter` installs only the adapter's requirements file, imports the adapter, and runs its tests.

**Verified:** 3 new tests, run in a fresh venv built from the requirements file with the CI job's exact steps; they fail on the old adapter. In the gateway's own environment the file is skipped (`mcp` is not installed there).

### Results

| Suite | Before (round 4) | After |
|---|---|---|
| gateway-api | 108 | 114 passed, 1 skipped (MCP tests; run by `mcp-adapter`) |
| mcp-adapter (own venv) | could not import | 3 passed |
| retrieval-service | 67 | 67 passed |
| integration | 5 | 5 passed |
| eval | 29 | 31 passed |
| agent eval gate | 36/36 | 45/45 (detector 0.90 / 0.78 unchanged) |
| ruff 0.14.0 | clean | clean |

### Not done

- `mcp>=2.0.0` is still unpinned in the adapter's requirements, as the original authors chose; CI installs whatever is newest (2.3.0 here).
- The live column of the eval report still has not been run.

## Round 6: unforgeable citation evidence, one ingest per collection at a time

Branch `improve/round-6`, stacked on `improve/round-5` (athish-shubhan/CodeSage#6).

### 1. Citation-shaped text inside retrieved content counted as evidence

**Found:** a flaw in the Round 0 citation checker. Evidence for a `search_code` result came from running the citation regex over the whole result, chunk bodies included, and `/chat` (Round 4) reused the same check. Reproduced three ways: a retrieved doc that mentions `[auth.py:5-12]` made a citation to `auth.py:5-12` grounded though `auth.py` was never shown; a planted line `[secrets.py:1-1000]` inside a chunk made `[secrets.py:40-41]` grounded and the real chunk's own range ungrounded; and `/chat` grounded `auth.py:5-12` from a README chunk that only mentions it. This repo's own docs (including this file) quote citations, so it happens with honest content too, not only planted text.

**Changed:** only header lines (`[path:start-end]` alone on a line) are evidence, and `escape_header_lines` prefixes a backslash to any line of retrieved content shaped exactly like a header, in `search_code` results, the `/chat` prompt, and the `/chat` check, so the model and the checker see the same defused text. Inline mentions are left as written.

**Verified:** 4 new tests (inline mention, forged header line, `search_code` escaping, `/chat` end to end); all 4 fail on the old code. The agent eval gate is unchanged at 45/45.

### 2. Concurrent ingests of one collection embedded the repo twice

**Found:** two `IngestRepo` calls on the same collection at once, which a retried RPC (the gateway's client retries `UNAVAILABLE`) or a double-submitted `/ingest` produces, each saw every file as changed. Measured with a 5-chunk repo and a slowed embedder: 10 chunks embedded for 5 chunks of content.

**Changed:** ingests of one collection are serialized per process; the second waits and finds nothing changed. Different collections do not wait for each other. Two replicas ingesting the same collection at the same time can still both do the work (documented).

**Verified:** the same measurement now embeds 5 chunks (one ingest embeds 5, the other 0); 2 new tests.

### Results

| Suite | Before (round 5) | After |
|---|---|---|
| gateway-api | 114 (+1 skipped) | 118 passed, 1 skipped |
| mcp-adapter (own venv) | 3 | 3 passed |
| retrieval-service | 67 | 69 passed |
| integration | 5 | 5 passed |
| eval | 31 | 31 passed |
| agent eval gate | 45/45 | 45/45 (detector 0.90 / 0.78 unchanged) |
| ruff 0.14.0 | clean | clean |

### Not done

- Ingest serialization is per process, not across replicas.
- The live column of the eval report still has not been run: no model weights are reachable from this environment (Hugging Face, the Ollama registry and GitHub releases are blocked by the proxy).

## Round 7: non-root containers, images started in CI

Branch `improve/round-7`, stacked on `improve/round-6` (athish-shubhan/CodeSage#7).

### 1. Both service images ran as root

**Found:** neither Dockerfile set a user, so `gateway-api` and `retrieval-service` ran as root in compose and k8s, and the k8s manifests had no `securityContext`. Both services index or serve repository content that is not trusted (ADR 0006), which is exactly where a process should not hold root.

**Changed:** both images create and switch to uid 10001 with a home directory (the embedding model downloads into `~/.cache/huggingface` at first use; nothing writes under `/app`). The k8s Deployments set `runAsNonRoot: true`, `runAsUser: 10001`, `allowPrivilegeEscalation: false` and drop all capabilities.

### 2. CI built the images but never started them

**Found:** `build-images` only checked that each image assembles; an image that builds but cannot start (a missing runtime dependency, a permissions problem such as the one item 1 could introduce) would pass.

**Changed:** the job now loads each image, starts it, waits up to 60 s for its health endpoint (`/livez` on the gateway, the metrics port on retrieval-service, which starts without Qdrant), and fails if `id -u` inside the container is 0.

### Verification

There is no Docker daemon in this environment, so neither change could be run here; the first run of both was this PR's CI. Both `build-images` jobs passed the new step on its first run (13/13 checks green): each image started, answered its health probe, and ran unprivileged; the gateway job's log reads `running as uid 10001`. The k8s files were checked to parse, as CI's `k8s-manifests` job does; they have not been applied to a cluster. No Python code changed, so the test suites are as in round 6.

### Not done

- `readOnlyRootFilesystem` is not set: retrieval-service needs a writable home for the model cache, which would need an `emptyDir` or a pre-downloaded model in the image.
- Compose does not set `user:`; it relies on the image's `USER`.

## Round 8: read-only root filesystems, a pinned MCP dependency

Branch `improve/round-8`, from `master` after rounds 1-7 merged.

### 1. Containers could write anywhere in their own filesystem

**Found:** left open in round 7. Both services run as uid 10001 but with a writable root filesystem, so anything that gets code execution in either container can modify the installed application and its dependencies. Neither service needs that: the gateway writes nothing, and retrieval-service writes only the embedding model download under `~/.cache`.

**Changed:** the k8s Deployments set `readOnlyRootFilesystem: true` with an `emptyDir` at `/tmp` for both and one at `/home/app/.cache` (1 GiB) for retrieval-service. Compose (main and edge) uses `read_only: true`, a tmpfs `/tmp`, and a named `model-cache` volume, which also means the model is no longer downloaded again after every container restart. The retrieval image creates `/home/app/.cache` as uid 10001: a named volume mounted where the image has no directory comes up owned by root, and the model download would fail.

**Verified in CI** (no Docker daemon here): `build-images` now starts each image with `--read-only --tmpfs /tmp` (plus the model-cache volume for retrieval-service), waits for its health endpoint, and checks that writing under `/app` fails and, for retrieval-service, that writing to the cache volume succeeds. The result is recorded in the PR. The k8s files were checked to parse; they have not been applied to a cluster.

### 2. The MCP adapter installed whatever `mcp` was newest

**Found:** `app/mcp/requirements.txt` had `mcp>=2.0.0`, so an `mcp` release could change or break the adapter without any change in this repo; every other dependency is pinned.

**Changed:** pinned to `mcp==2.3.0`, the version the `mcp-adapter` CI job has been testing.

**Verified:** a fresh venv from the requirements file installs 2.3.0, imports the adapter, and passes its 3 tests.

### Results

No Python code changed: gateway-api 118 passed (1 skipped), retrieval-service 69, integration 5, eval 31, agent eval gate 45/45, ruff clean (run on this branch).

### Not done

- Ingest across replicas is still unserialized (see round 6): fixing it needs a lease in shared storage or routing every ingest to one replica, a design choice rather than a local fix.
- The live column of the eval report still needs a reachable LLM.

## Round 9: streaming agent runs, citation repair, request ids across services

Branch `improve/round-9`, stacked on `improve/round-8` (athish-shubhan/CodeSage#9). This round adds features rather than fixing defects.

### 1. `POST /agent/stream`: an agent run as server-sent events

**Why:** an agent run takes several LLM round-trips and tool calls, up to the 60 s deadline, and `POST /agent` answered only at the end.

**Added:** the same run streamed as `step`, `tool_call` (name, arguments), `tool_result` (size, injection-guard removals) and `repair` events while it works, then one `answer` event with the full response (citations, flags, request id) or one `error` event (same categories as the REST errors). The loop takes an optional event callback, so `POST /agent` is unchanged. A client that disconnects cancels the run, so it stops spending LLM and tool calls nobody will read.

**Verified:** 4 tests: the event sequence and final answer for a run that reads the injected fixture file, an error event for a malformed LLM response, auth required, and cancellation of a hung LLM call when the stream is closed.

### 2. Citation repair (opt-in, `GATEWAY_AGENT_REPAIR_CITATIONS`)

**Why:** rounds 0-6 made the gateway good at detecting ungrounded citations and invented names, but only reported them. The agent can use that verdict to fix its own answer.

**Added:** when a final answer fails the checks, the loop sends one more turn listing exactly which citations point at nothing a tool returned and which names are not in the cited text, and asks the model to revise, check with the tools, or say what it could not verify. At most one repair per run, only if a step is left, and the revision is checked and returned whatever it says. Exposed as `repairs` in the response and audit log, and `agent_citation_repairs_total{resolved}`. Off by default: it adds an LLM round-trip to failing answers, and `/agent` behaves exactly as before unless enabled.

**Verified:** 6 tests (feedback content, the repaired answer's verdict, off by default, passing answers not sent back, one repair at most, no repair without a step left) and a new eval case: replay passes 49/49 label checks (was 45/45), and the repair case fails with repair disabled. Whether repair helps a real model is not measured; `eval/agent_eval.py --live` runs that case against one.

### 3. One request id across the gateway, retrieval-service, and the audit log

**Why:** a failing request touched two services and an audit file with nothing linking their log lines.

**Added:** ASGI middleware takes the client's `X-Request-ID` when it is a safe token, otherwise generates one, and echoes it in the response header. The gateway's log lines and the audit log carry it; `rag_client` sends it as `x-request-id` gRPC metadata on every RPC; retrieval-service sets it per RPC (reset afterwards, since RPCs share worker threads) and logs one line per RPC with its duration.

**Verified:** 9 gateway tests (echo, replacement of missing and unsafe ids, audit log, response field, gRPC metadata, log filter) and 1 integration test over real gRPC showing retrieval-service sees the gateway's id during the RPC and resets it after.

### Results

| Suite | Before (round 8) | After |
|---|---|---|
| gateway-api | 118 (+1 skipped) | 137 passed, 1 skipped |
| retrieval-service | 69 | 69 passed |
| integration | 5 | 6 passed |
| eval | 31 | 32 passed |
| agent eval gate | 45/45 | 49/49 (12 cases) |
| ruff 0.14.0 | clean | clean |

### Not done

- The streaming endpoint is not proxied through `/ws/chat`; WebSocket clients still get `/chat` only.
- Repair's effect on answer quality needs a live model to measure.
