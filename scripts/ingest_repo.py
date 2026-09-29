#!/usr/bin/env python3
"""CLI to trigger repo ingestion against a running gateway-api.

Usage:
    python scripts/ingest_repo.py --repo-path /data/some-repo --username admin --password admin
"""
from __future__ import annotations

import argparse
import sys

import httpx


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gateway-url", default="http://localhost:8000")
    parser.add_argument("--repo-path", required=True, help="Path as seen inside the retrieval-service container")
    parser.add_argument("--collection", default="codebase")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="admin")
    args = parser.parse_args()

    with httpx.Client(timeout=600) as client:
        token_resp = client.post(
            f"{args.gateway_url}/token",
            data={"username": args.username, "password": args.password},
        )
        token_resp.raise_for_status()
        token = token_resp.json()["access_token"]

        resp = client.post(
            f"{args.gateway_url}/ingest",
            json={"repo_path": args.repo_path, "collection": args.collection},
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        print(resp.json())
    return 0


if __name__ == "__main__":
    sys.exit(main())
