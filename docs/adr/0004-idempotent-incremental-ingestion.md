# 0004: Idempotent, incremental ingestion with Qdrant as the only durable store

**Status:** accepted

## Context

The original ingest path chunked and embedded every file on every call and wrote points with random UUIDs. Reproduced against the old code: ingesting the same 289 chunks twice left 578 points in the collection. The BM25 index and the repo-root mapping (used by `expand_context` and `get_file`) lived only in process memory. After a restart, or on the second of two k8s replicas, lexical search returned nothing and file reads failed until someone re-ingested.

## Options

1. Keep full re-ingest, and delete the collection first.
2. Add a second store (SQLite, Redis) for file hashes, the BM25 index, and repo roots.
3. Make Qdrant payloads carry everything needed to rebuild the in-memory state.

## Decision

Option 3. Each chunk payload stores `file_hash` (SHA-256 of the file) and `repo_root`. Point IDs are `uuid5(collection, path, line range, file_hash)`. On ingest, files whose hash matches the stored one are skipped, changed files have their old chunks deleted and new ones embedded, and files gone from the repo are deleted. The BM25 index and repo root are rebuilt from payloads on first use after a restart (`pipeline.restore`).

## Why

- Embedding is the expensive step, so skipping unchanged files skips almost all of the work. Measured on this repo with `scripts/bench_ingest.py` (105 files, 353 chunks): an unchanged re-ingest embeds 0 chunks instead of 353, editing README.md re-embeds its 3 chunks, and deleting a file removes its chunk without embedding anything.
- No new infrastructure. Deleting the collection first (option 1) would make search return nothing during every re-ingest.

## Trade-offs

- Every ingest scrolls all payloads to read the stored hashes. That is fine at thousands of chunks; at millions it would want a payload index or a separate manifest.
- A replica that already rebuilt its BM25 index does not notice a later ingest done through another replica until it restarts. This only affects the non-default `hybrid` and `lexical` strategies (ADR 0002). `expand_context` and `get_file` read from disk and are unaffected.
- Deletion detection is skipped for glob-scoped ingests, since files outside the glob were never scanned.
