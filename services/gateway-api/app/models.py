from pydantic import BaseModel


class ChatRequest(BaseModel):
    question: str
    collection: str | None = None
    top_k: int | None = None


class ChatResponse(BaseModel):
    answer: str
    sources: list[dict]


class IngestRequest(BaseModel):
    repo_path: str
    collection: str | None = None
    include_globs: list[str] | None = None


class IngestResponse(BaseModel):
    files_indexed: int  # files scanned
    chunks_indexed: int  # chunks in the collection after this ingest
    files_changed: int  # new or modified since the last ingest, re-embedded
    files_removed: int  # deleted from the repo, their chunks dropped
    chunks_embedded: int  # embedding work this call actually did
