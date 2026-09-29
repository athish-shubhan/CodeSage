"""Optional LLM-judge pass for answer quality. Explicitly not a hard gate.

Retrieval quality (run_eval.py) and citation faithfulness (citation_check.py)
are both deterministic and don't need this. This exists for the one thing
they can't measure: whether the generated *prose* is actually a good
answer. LLM judges are noisy and backend-dependent, so this stays opt-in
and is never wired into CI.
"""
from __future__ import annotations

import argparse
import json
import os

import httpx

LLM_BASE_URL = os.environ.get("EVAL_LLM_BASE_URL", "http://localhost:11434/v1")
LLM_MODEL = os.environ.get("EVAL_LLM_MODEL", "llama3.1:8b-instruct-q4_0")

JUDGE_PROMPT = """You are grading a coding assistant's answer for a Q&A benchmark.
Question: {question}
Answer: {answer}

Score the answer's relevance and correctness from 1 (unrelated/wrong) to 5
(directly and correctly answers the question). Respond with ONLY a JSON
object: {{"score": <1-5>, "reason": "<one sentence>"}}"""


def judge(question: str, answer: str) -> dict:
    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": JUDGE_PROMPT.format(question=question, answer=answer)}],
        "stream": False,
    }
    resp = httpx.post(f"{LLM_BASE_URL}/chat/completions", json=payload, timeout=60)
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {"score": None, "reason": f"judge returned non-JSON: {content[:200]}"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Optional, not a CI gate; see module docstring.")
    parser.add_argument("question")
    parser.add_argument("answer")
    args = parser.parse_args()
    print(json.dumps(judge(args.question, args.answer), indent=2))
