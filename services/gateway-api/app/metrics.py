"""Agent-layer Prometheus metrics. Request-level HTTP metrics (rate,
latency) already come from `prometheus_fastapi_instrumentator` in main.py --
these are the metrics that instrumentator can't see: what happens *inside*
an agent run."""
from prometheus_client import Counter, Histogram

AGENT_STEPS = Histogram("agent_steps_total", "Number of LLM round-trips per agent run", buckets=(1, 2, 3, 4, 5))
AGENT_TOOL_CALLS = Counter("agent_tool_calls_total", "Total tool invocations across all agent runs", ["tool"])
AGENT_STOP_REASON = Counter("agent_stopped_reason_total", "Why an agent run ended", ["reason"])
