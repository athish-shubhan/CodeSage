# 0002: Dense-only retrieval by default, hybrid and rerank opt-in

**Status:** accepted (re-check when the corpus changes)

## Context

The retrieval-service implements dense search (Qdrant), lexical search (bm25s), weighted reciprocal rank fusion driven by a regex query classifier, and an optional cross-encoder reranker. The common assumption is that hybrid search beats dense search for code, because identifiers are exact-match tokens.

## Options

1. Hybrid by default (the original design).
2. Dense by default, hybrid and rerank selectable per request.
3. Hybrid plus reranking by default.

## Decision

Dense by default. `strategy` and `use_reranker` on `SearchRequest` keep the other modes available.

## Why

`eval/ablation.py` on this repository (22 questions, docs/evaluation.md):

| Strategy | Recall@5 | MRR | Avg latency |
|---|---|---|---|
| Dense | 0.70 | 0.51 | 1056 ms |
| Hybrid | 0.70 | 0.45 | 760 ms |
| Hybrid + rerank | 0.80 | 0.49 | 26018 ms |

Hybrid tied dense on recall and lost on MRR. Reranking bought +0.10 recall for about 25x latency on CPU, which is not acceptable for an interactive request.

## Trade-offs

- The benchmark is small (22 questions, one corpus), so this is a default, not a law. A larger, more identifier-heavy corpus could flip it, which is why the ablation is a script and not a one-off.
- Keeping hybrid available means keeping the BM25 index and its restore logic, even though the default path does not use them.

## Consequences

The eval harness, not intuition, decides the default. Changing it means re-running `make eval` and updating this record.
