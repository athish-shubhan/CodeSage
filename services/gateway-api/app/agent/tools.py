"""Agent tools: the only capabilities the agent loop can invoke. Each has a
Pydantic argument schema (validated before the call reaches the underlying
gRPC client) and returns plain text for the LLM to read back.

Deliberately three tools, not every internal capability turned into a
tool: search, look at more of what search found, or read a whole file.
That covers what a codebase question needs beyond a single retrieval call.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app import rag_client

MAX_FILE_BYTES = 20_000


class SearchCodeArgs(BaseModel):
    query: str
    top_k: int = Field(default=5, ge=1, le=15)


class ExpandContextArgs(BaseModel):
    source_path: str
    start_line: int
    end_line: int
    extra_lines: int = Field(default=20, ge=1, le=200)


class GetFileArgs(BaseModel):
    source_path: str


async def search_code(args: SearchCodeArgs) -> str:
    hits = await rag_client.search(args.query, top_k=args.top_k)
    if not hits:
        return "No matching code found."
    return "\n\n".join(f"[{h['source_path']}:{h['start_line']}-{h['end_line']}]\n{h['text']}" for h in hits)


async def expand_context(args: ExpandContextArgs) -> str:
    text = await rag_client.expand_context(args.source_path, args.start_line, args.end_line, args.extra_lines)
    return text or f"Could not expand context for {args.source_path}:{args.start_line}-{args.end_line}."


async def get_file(args: GetFileArgs) -> str:
    result = await rag_client.get_file(args.source_path, MAX_FILE_BYTES)
    if result is None:
        return f"File not found: {args.source_path}"
    suffix = "\n... (truncated)" if result["truncated"] else ""
    return result["text"] + suffix


_REGISTRY: dict[str, tuple[type[BaseModel], object]] = {
    "search_code": (SearchCodeArgs, search_code),
    "expand_context": (ExpandContextArgs, expand_context),
    "get_file": (GetFileArgs, get_file),
}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "Search the indexed codebase for chunks relevant to a query. "
            "Use for sub-questions the initial retrieval didn't cover.",
            "parameters": SearchCodeArgs.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "expand_context",
            "description": "Fetch more surrounding lines around a chunk you already have "
            "(from search_code results) to see fuller context.",
            "parameters": ExpandContextArgs.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_file",
            "description": "Read a whole source file by its repo-relative path (size-bounded).",
            "parameters": GetFileArgs.model_json_schema(),
        },
    },
]


async def call_tool(name: str, raw_args: dict) -> str:
    if name not in _REGISTRY:
        return f"Unknown tool: {name}"
    schema_cls, fn = _REGISTRY[name]
    try:
        args = schema_cls(**raw_args)
    except Exception as exc:
        return f"Invalid arguments for {name}: {exc}"
    try:
        return await fn(args)
    except Exception as exc:
        return f"Tool {name} failed: {exc}"
