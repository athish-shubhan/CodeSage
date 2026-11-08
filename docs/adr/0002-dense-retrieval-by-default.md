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

The original choice rested on an ablation of 22 questions (hybrid tied dense on Recall@5 and had a lower MRR; reranking gave +0.10 recall at about 25x latency). That table was re-run on the current 28-question file with `make eval-local` (20 answerable questions, details in docs/evaluation.md):

| Strategy | Recall@5 | MRR | p50 latency |
|---|---|---|---|
| Dense | 0.60 (12/20) | 0.47 | 10 ms |
| Hybrid | 0.70 (14/20) | 0.55 | 11 ms |
| Hybrid + rerank | 0.60 (12/20) | 0.47 | 1134 ms |

The ordering changed between the two runs: hybrid now leads by two questions and the reranker no longer helps. With 20 answerable questions the 95% bootstrap intervals (0.40-0.80 for dense, 0.50-0.90 for hybrid) overlap heavily, so neither run separates the strategies. Dense stays the default because it is simpler (no BM25 index to build and restore) and because there is no separable measured advantage for hybrid, not because hybrid was shown to be worse. Reranking costs about 100x the latency on CPU and has not shown a recall gain in the current run, which is not acceptable for an interactive request.

## Trade-offs

- The benchmark is small (28 questions, 20 answerable, one corpus), so this is a default, not a law. The latest run leans toward hybrid; a larger question set could justify switching, which is why the ablation is a script and not a one-off.
- Keeping hybrid available means keeping the BM25 index and its restore logic, even though the default path does not use them.

## Consequences

The eval harness, not intuition, decides the default. Changing it means re-running `make eval-local` (or `make eval` against a Qdrant server) and updating this record.
