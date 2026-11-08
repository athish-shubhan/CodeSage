# Evaluation

This is what running `eval/` against this repo's own content actually found, not a projection of what it should find. See `eval/README.md` for how to reproduce it.

## Setup

28 hand-written questions (`eval/qa_pairs.jsonl`) against this repository ingested as its own corpus: 136 files, 657 chunks after AST-aware chunking (a `git archive` of commit `db35040`). 20 are answerable (5 each of exact identifier lookup, semantic/paraphrase, cross-file and code-specific) and 8 are unanswerable (their topics appear nowhere in the repo), used to check the system does not confidently return irrelevant files. Recall@5 and MRR are computed over the 20 answerable questions only.

Ground truth is the expected source file(s) per question, not exact line ranges, since AST chunking boundaries can shift slightly without changing which file holds the answer.

## Retrieval strategy comparison

Run with `make eval-local` (in-memory Qdrant, no Docker, CPU embeddings with `all-MiniLM-L6-v2`, cross-encoder `ms-marco-MiniLM-L-6-v2` for the rerank row) on the current 28-question file, one run on an 8 GB Apple M1; the raw output is `eval/report.md`. Intervals are 95% bootstrap intervals over the 20 answerable questions.

| Strategy | Recall@5 (answerable, n=20) | Recall 95% CI | MRR | p50 latency | p95 latency | Avg context tokens |
|---|---|---|---|---|---|---|
| Dense only (Qdrant) | 0.60 (12/20) | 0.40-0.80 | 0.47 | 10 ms | 13 ms | 1539 |
| Lexical only (bm25s) | 0.60 (12/20) | 0.40-0.80 | 0.37 | 1 ms | 1 ms | 1380 |
| Hybrid (dense + lexical, fused) | 0.70 (14/20) | 0.50-0.90 | 0.55 | 11 ms | 13 ms | 1576 |
| Hybrid + reranker | 0.60 (12/20) | 0.40-0.80 | 0.47 | 1134 ms | 1642 ms | 1719 |

This replaces an earlier table that was computed on a 22-question set (20 answerable, 2 unanswerable) with a Docker Qdrant on 2 CPUs; none of those numbers are reused. The latencies here are per-query times against an in-process Qdrant and are not comparable with the earlier ones (which included gRPC to a Qdrant server and CPU contention). The average-context-token column is measured after the `fusion.assemble_context` fix that made earlier values an upper bound.

**What the table shows.** With 20 answerable questions one question moves Recall@5 by 0.05, and all four intervals overlap heavily, so no row is a statistically separable result. Hybrid fusion has the best point estimates (14 of 20 questions with the expected file in the top 5, against 12 of 20 for dense), and its MRR is higher (0.55 vs 0.47), at no meaningful latency cost in this setup. Lexical-only ties dense on recall but ranks the right file lower (MRR 0.37). The reranker did not improve recall over dense here (12/20) and costs about 100x the latency (1.1 s vs 10 ms on this CPU).

**This differs from the earlier run.** The earlier table had hybrid tying dense and the reranker winning (0.80); now hybrid leads and the reranker ties dense. Between the two runs the question set, the corpus (this repository grew), the Qdrant deployment and the context-token accounting all changed, so the change in ordering is what you would expect from noise at this size, and neither ordering should be relied on.

**The default is still dense-only**, for simplicity (no BM25 index to build and restore) and because the evidence on this corpus does not separate the strategies. It is not supported by a measured advantage, and the current run, if anything, leans toward hybrid. Hybrid and rerank stay selectable per request (`strategy`, `use_reranker` on `SearchRequest`); a larger question set is what would justify changing the default, and [ADR 0002](adr/0002-dense-retrieval-by-default.md) says so.

## Unanswerable questions

`Search` returns up to `top_k` results with no relevance-score cutoff by default (`min_score` is 0), so for all 8 unanswerable questions every strategy returns "closest available" chunks, not an empty result: the clean-rate is 0 of 8 by construction. A relevance threshold would improve this at the cost of sometimes dropping a real but weakly-scored match; `eval/abstention.py` sweeps it, and it is off by default.

## Agent reliability

`eval/agent_eval.py` covers the `/agent` reliability layer (`docs/adr/0006-untrusted-tool-output.md`); its measured numbers are in the agent-reliability section of `eval/report.md`. What it does and does not show:

- Measured without an LLM (CI gate): the injection guard removes the fixture's injected comment before any LLM call in all 4 cases where it is fetched (3 through `/agent` tools, 1 through `/chat` retrieval), records it at the right file lines, and makes citations to it ungrounded; the citation, unsupported-identifier, and abstention verdicts match hand labels in all 49 checks (including a citation-repair case); the regex detector catches 18 of 23 labeled injections and flags 2 of 20 benign sentences; in 47 ordinary code and doc files of this repo it flags one sentence, a README line describing this feature, which shows the kind of false positive to expect from prose about LLMs.
- Only measured once with a live model, and thinly: how often a model's citations are grounded, how often it names identifiers its citations do not contain, whether it abstains on unanswerable questions, and whether it follows injections the regex misses. A first live run is recorded in `docs/results/agent_eval_live.md` (see the README for its numbers and caveats); it is one run of a 3B model over 12 cases. The replay rates in the report are computed over scripted answers that are bad on purpose, so they check the arithmetic, not a model.
- The labeled sentences and the cases were written by the same person as the rules, so they guard against regressions rather than estimate real-world detection rates.

## Reproducing this

```bash
make eval-local     # no Docker: in-memory Qdrant, ingests a git archive of HEAD, writes eval/report.md
```

Needs the retrieval-service and eval requirements installed (`pip install -r services/retrieval-service/requirements.txt -r eval/requirements.txt`); the first run downloads the embedding and reranker models. With a Qdrant server instead: `make up`, `make ingest-self`, `make eval` (this ingests the working tree rather than a `git archive`, so the corpus differs slightly).

## What this does and doesn't claim

This is a 28-question benchmark (20 answerable) on a roughly 136-file corpus, one run. It is not a claim of statistical significance, and the specific Recall@K/MRR numbers above will shift with corpus size, embedding model choice, and the exact question set. What it does demonstrate is a working, reusable measurement pipeline: point it at any ingested corpus and it produces the same comparison, rather than assuming which retrieval strategy is better.
