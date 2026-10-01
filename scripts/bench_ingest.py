"""How much embedding work an ingest does: first ingest, unchanged re-ingest,
one edited file, one deleted file. Runs the real chunker and ingest
pipeline against an embedded Qdrant, on a temporary copy of this repo's
git-tracked files. The embedding model is replaced with a hashed
bag-of-words stand-in because the number measured, chunks sent to the
embedder, does not depend on which model does the embedding.

    python scripts/bench_ingest.py
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ["QDRANT_URL"] = ":memory:"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "retrieval-service"))

import pipeline  # noqa: E402

DIM = 64


def stand_in_embed(texts: list[str]) -> list[list[float]]:
    vectors = []
    for text in texts:
        v = [0.0] * DIM
        for token in text.split():
            v[int(hashlib.md5(token.encode()).hexdigest(), 16) % DIM] += 1.0
        norm = sum(x * x for x in v) ** 0.5 or 1.0
        vectors.append([x / norm for x in v])
    return vectors


def copy_tracked_files(dest: Path) -> None:
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    for rel in files:
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, target)


def main() -> None:
    pipeline.embed = stand_in_embed
    pipeline.embedding_dim = lambda: DIM
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        copy_tracked_files(repo)
        steps = [
            ("first ingest", None),
            ("unchanged re-ingest", None),
            ("one file edited", lambda: (repo / "README.md").open("a").write("\nedited\n")),
            ("one file deleted", lambda: (repo / "scripts" / "smoke_test.sh").unlink()),
        ]

        print("| Step | Files scanned | Files changed | Files removed | Chunks embedded | Chunks in index |")
        print("|---|---|---|---|---|---|")
        for label, mutate in steps:
            if mutate:
                mutate()
            r = pipeline.ingest("bench", str(repo))
            print(f"| {label} | {r.files_seen} | {r.files_changed} | {r.files_removed} | {r.chunks_embedded} | {r.chunks_total} |")


if __name__ == "__main__":
    main()
