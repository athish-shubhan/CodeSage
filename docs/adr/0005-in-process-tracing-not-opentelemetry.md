# 0005: In-process trace spans, not OpenTelemetry (yet)

**Status:** accepted, revisit when the GenAI conventions stabilize or a second team needs traces

## Context

Debugging a bad answer needs to show what each retrieval stage did and how long it took. OpenTelemetry is the standard for distributed traces, and its GenAI semantic conventions define spans for model calls, agent invocations, and tool execution.

## Options

1. OpenTelemetry SDK in both services, an OTLP collector, and Jaeger or Tempo.
2. A small in-process `Trace` (list of timed spans) returned in the `SearchResponse`, plus Prometheus metrics for aggregates.

## Decision

Option 2.

## Why

- One consumer of trace data (the person debugging or the eval harness) and two services. A collector, a trace store, and a UI are three more containers to run and size for that.
- As of this writing, the OpenTelemetry GenAI semantic conventions are still marked "Development" and moved to their own repository in mid-2026 without a stable release. Instrumenting against attribute names that may still change would mean redoing it.
- Aggregate questions (how often does the agent time out, how many citations are ungrounded, how much embedding did ingest do) are answered by Prometheus counters that already exist.

## Trade-offs

- No cross-service trace correlation. A slow `/agent` request cannot be followed from the gateway into the retrieval-service in one view.
- Moving to OpenTelemetry later means replacing `tracing.py`'s spans with OTel spans. The span boundaries (classify, dense, lexical, fuse, rerank, assemble) would carry over unchanged.

## References

- OpenTelemetry GenAI semantic conventions status: https://www.greptime.com/blogs/2026-05-09-opentelemetry-genai-semantic-conventions
