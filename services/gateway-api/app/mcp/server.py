"""MCP adapter: exposes CodeSage's retrieval capability to external MCP
clients (Claude Desktop, other agents) over stdio.

Deliberately peripheral: this wraps `app.rag_client` (the same,
already-tested gRPC client `/chat` and `/agent` use) rather than
duplicating retrieval logic, but the gateway's own `/agent` loop does NOT
route through this. Adding a subprocess/stdio hop to the gateway's own
critical path would buy nothing. This exists purely so *other* tools can
reuse CodeSage's retrieval without reimplementing the gRPC client.

Run in its own environment (see requirements.txt in this directory),
NOT installed alongside gateway-api's main requirements.txt. The `mcp`
package pulls a starlette version incompatible with the pinned FastAPI
build; keeping this process's dependencies separate avoids that conflict
entirely rather than papering over it with unpinned versions.

    pip install -r app/mcp/requirements.txt
    python -m app.mcp.server
"""
from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from app import rag_client

mcp = MCPServer(name="codesage-retrieval")


@mcp.tool()
async def search_code(query: str, top_k: int = 5) -> str:
    """Search the indexed codebase for chunks relevant to a query."""
    hits = await rag_client.search(query, top_k=top_k)
    if not hits:
        return "No matching code found."
    return "\n\n".join(f"[{h['source_path']}:{h['start_line']}-{h['end_line']}]\n{h['text']}" for h in hits)


@mcp.tool()
async def expand_context(source_path: str, start_line: int, end_line: int, extra_lines: int = 20) -> str:
    """Fetch more surrounding lines around a chunk from its source file."""
    text = await rag_client.expand_context(source_path, start_line, end_line, extra_lines)
    return text or f"Could not expand context for {source_path}:{start_line}-{end_line}."


if __name__ == "__main__":
    mcp.run(transport="stdio")
