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
    files_indexed: int
    chunks_indexed: int
