#!/usr/bin/env python3
"""Demo client: ingest a small repo, ask a question, stream a cited answer.

Talks to a running gateway-api (see scripts/demo.sh, or `make up`).
Ingest is idempotent, so running it twice re-embeds nothing.

    python scripts/demo.py --repo-path /path/seen/by/retrieval-service \
        --question "Does refund_payment require approval for large refunds?"
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

import httpx
import websockets

DEFAULT_QUESTION = "Does refund_payment require approval for large refunds?"


async def ask(base: str, token: str, question: str) -> dict:
    ws_url = base.replace("http", "ws", 1) + f"/ws/chat?token={token}"
    t0 = time.perf_counter()
    first_token = None
    async with websockets.connect(ws_url, max_size=None) as ws:
        await ws.send(json.dumps({"question": question}))
        while True:
            msg = json.loads(await ws.recv())
            if msg["type"] == "sources":
                print("retrieved:")
                for s in msg["sources"]:
                    print(f"  {s.get('source_path')}:{s.get('start_line')}-{s.get('end_line')}")
                for f in msg["injection_flags"]:
                    print(f"  removed instruction-like text ({f['rule']}) in {f.get('source_path')}:{f.get('start_line')}")
                print("\nanswer:")
            elif msg["type"] == "token":
                if first_token is None:
                    first_token = time.perf_counter() - t0
                print(msg["text"], end="", flush=True)
            elif msg["type"] == "done":
                total = time.perf_counter() - t0
                c = msg["citations"]
                print("\n")
                print(f"grounded citations:   {c['grounded']}")
                print(f"ungrounded citations: {c['ungrounded']}")
                if first_token is not None:
                    print(f"time to first token {first_token:.1f}s, total {total:.1f}s")
                return msg
            elif msg["type"] == "error":
                print(f"\nerror: {msg['detail']}", file=sys.stderr)
                raise SystemExit(1)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--gateway-url", default="http://localhost:8000")
    p.add_argument("--repo-path", required=True, help="path as seen by retrieval-service")
    p.add_argument("--collection", default="codebase")
    p.add_argument("--question", default=DEFAULT_QUESTION)
    p.add_argument("--username", default="admin")
    p.add_argument("--password", default="admin")
    a = p.parse_args()

    with httpx.Client(timeout=600) as c:
        tok = c.post(f"{a.gateway_url}/token", data={"username": a.username, "password": a.password})
        tok.raise_for_status()
        token = tok.json()["access_token"]
        t0 = time.perf_counter()
        r = c.post(
            f"{a.gateway_url}/ingest",
            json={"repo_path": a.repo_path, "collection": a.collection},
            headers={"Authorization": f"Bearer {token}"},
        )
        r.raise_for_status()
        j = r.json()
        print(f"ingested {j['files_indexed']} files -> {j['chunks_indexed']} chunks "
              f"({j['chunks_embedded']} embedded) in {time.perf_counter() - t0:.1f}s\n")

    print(f"question: {a.question}\n")
    # /ws/chat searches the gateway's default collection ("codebase"), so ingest into that.
    asyncio.run(ask(a.gateway_url, token, a.question))
    return 0


if __name__ == "__main__":
    sys.exit(main())
