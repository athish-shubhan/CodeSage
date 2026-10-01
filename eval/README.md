# Evaluation harness

A reusable evaluation pipeline for the retrieval/context layer, run against a live `retrieval-service`.

## What's here

- `qa_pairs.jsonl`: 28 hand-written questions against this repo's own content: 20 answerable across four categories (exact_identifier, semantic, cross_file, code_specific) and 8 unanswerable ones whose topics appear nowhere in the repo. Ground truth is the expected source file(s), not exact line ranges, since chunk boundaries shift with the AST chunker but file identity doesn't.
- `run_eval.py`: Recall@K with a seeded bootstrap 95% interval, MRR, p50/p95 latency, average context tokens, and each question's best dense similarity. Deterministic; knowing whether the right file came back doesn't need an LLM judge.
- `citation_check.py`: a deterministic faithfulness check, whether a generated answer only cites files that were actually retrieved for it.
- `ablation.py`: runs `run_eval.py` across dense-only, lexical-only, hybrid, and hybrid+rerank configurations and writes `report.md`.
- `abstention.py`: from one dense run, sweeps a similarity threshold and shows how many unanswerable questions it would catch and how much Recall@K it would cost. Use it to pick a value for `GATEWAY_RETRIEVAL_MIN_SCORE`, which defaults to 0 (off) until that sweep has been run and recorded.
- `llm_judge.py`: optional, not a CI gate. LLM judges are noisy and backend-dependent; use it by hand for a prose-quality read the deterministic checks can't give.
- `fixture/`: a tiny fixed corpus and 5 question/answer pairs used by the CI retrieval-smoke job, kept separate from `qa_pairs.jsonl` so CI stays fast and independent of this repo's evolving content.

## Running it

```bash
pip install -r requirements.txt

# from the repo root, with the stack up and `make ingest-self` already run
python -m grpc_tools.protoc -I services/retrieval-service/proto \
    --python_out=eval --grpc_python_out=eval \
    services/retrieval-service/proto/retrieval.proto

cd eval
python run_eval.py --strategy dense
python ablation.py          # writes report.md
```

Or `make eval` from the repo root, which does both steps.

## Scale

N=22 is a demo-scale benchmark on a roughly 95-file corpus, not a claim of statistical significance. The harness itself is corpus-agnostic: point `--collection` at a larger ingested repo and it scales. See `docs/evaluation.md` for what running it actually found.
