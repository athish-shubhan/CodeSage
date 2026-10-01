# Evaluation harness

A reusable evaluation pipeline for the retrieval/context layer, run against a live `retrieval-service`.

## What's here

- `qa_pairs.jsonl`: 22 hand-written question/answer pairs against this repo's own content, across five categories (exact_identifier, semantic, cross_file, code_specific, unanswerable). Ground truth is the expected source file(s), not exact line ranges, since chunk boundaries shift with the AST chunker but file identity doesn't.
- `run_eval.py`: Recall@K, MRR, average latency, average context tokens. Deterministic; knowing whether the right file came back doesn't need an LLM judge.
- `citation_check.py`: a deterministic faithfulness check, whether a generated answer only cites files that were actually retrieved for it.
- `ablation.py`: runs `run_eval.py` across dense-only, lexical-only, hybrid, and hybrid+rerank configurations and writes `report.md`.
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
