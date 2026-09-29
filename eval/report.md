# CodeSage retrieval ablation report

N = 22 hand-written questions against this repo's own content (collection=codebase). Small-N by design: this is a demo-scale benchmark, not a claim of statistical significance. The harness itself is corpus-agnostic.

| Strategy | Recall@K | MRR | Avg latency (ms) | Avg context tokens |
|---|---|---|---|---|
| dense only | 0.70 | 0.51 | 1056 | 2155 |
| lexical (BM25) only | 0.55 | 0.40 | 32 | 2504 |
| hybrid (dense + lexical, fused) | 0.70 | 0.45 | 760 | 2442 |
| hybrid + reranker | 0.80 | 0.49 | 26018 | 2010 |

**Finding:** hybrid + reranker improved Recall@K by +0.10 over dense-only (0.70 -> 0.80), at +24962ms extra average latency.