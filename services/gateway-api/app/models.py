from pydantic import BaseModel, Field

from app.config import settings

MAX_TOP_K = 50  # retrieval-service fetches 20 candidates per strategy, so more than this cannot help


class ChatRequest(BaseModel):
    question: str = Field(max_length=settings.max_question_chars)
    collection: str | None = None
    top_k: int | None = Field(default=None, ge=1, le=MAX_TOP_K)


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
