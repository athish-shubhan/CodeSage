# 0003: A native bounded agent loop instead of an agent framework

**Status:** accepted

## Context

`POST /agent` lets the model call `search_code`, `expand_context`, and `get_file` across several steps before answering.

## Options

1. LangGraph (or a similar graph framework).
2. A plain Python loop over the OpenAI-compatible tool-calling API.

## Decision

A plain loop (`app/agent/loop.py`, under 120 lines) with three hard bounds: `MAX_STEPS=4`, `MAX_TOOL_CALLS=6`, and a `TIMEOUT_S=60` deadline enforced with `asyncio.timeout` around the whole run.

## Why

- Three tools and a four-step cap is a loop, not a graph. A framework would add a dependency and an abstraction layer without removing any code that matters.
- Every behaviour that matters is visible and unit-tested in one file: the deadline cancels an in-flight LLM call, tool calls within a step run concurrently, every `tool_call` id gets a `tool` reply even when the budget cuts the batch short, and the final answer's citations are checked against what the tools returned.

## Trade-offs

- No built-in persistence, human-in-the-loop interrupts, or branching. None are needed for a single-request research loop; if they become needed, that is the point to revisit.
- Model capability is the real limit. Live tests with a 0.5B model showed it often ignores tools or writes a fake call as text. The loop handles that (it treats a plain-text answer as final), but the answer quality depends on running a tool-tuned model.

## Consequences

Two bugs were found and fixed while hardening this loop. The timeout was originally only checked between steps, so a hung backend could hold a request for up to 4 x 60 s. Also, tool calls dropped by the budget never got a `tool` message, which OpenAI-compatible servers reject on the next turn.
