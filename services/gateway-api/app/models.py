from pydantic import BaseModel, Field

from app.config import settings

MAX_TOP_K = 50  # retrieval-service fetches 20 candidates per strategy, so more than this cannot help


class UnsupportedIdentifier(BaseModel):
    identifier: str  # a code name or path the answer attributes to the citations below
    citations: list[str]  # "path:start-end"; none of their tool text contains the identifier


class Citations(BaseModel):
    grounded: list[str]  # "path:start-end" backed by a tool result in this run
    ungrounded: list[str]  # cited by the model, never shown to it by a tool (or only as removed text)
    unsupported_identifiers: list[UnsupportedIdentifier] = []


class InjectionFlag(BaseModel):
    tool: str  # the agent tool whose result held it, or "retrieval" on /chat
    rule: str  # which app/agent/untrusted.py rule matched
    text: str  # the removed sentence (truncated)
    source_path: str | None = None
    start_line: int | None = None
    end_line: int | None = None


class ChatRequest(BaseModel):
    question: str = Field(max_length=settings.max_question_chars)
    collection: str | None = None
    top_k: int | None = Field(default=None, ge=1, le=MAX_TOP_K)


class ChatResponse(BaseModel):
    answer: str
    sources: list[dict]  # as retrieved; the prompt got these with instruction-like text removed
    citations: Citations = Citations(grounded=[], ungrounded=[])  # checked against the sources
    injection_flags: list[InjectionFlag] = []


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
