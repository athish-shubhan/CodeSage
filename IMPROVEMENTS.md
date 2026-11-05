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
