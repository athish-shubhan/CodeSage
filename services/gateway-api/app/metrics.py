"""Agent-layer Prometheus metrics. Request-level HTTP metrics (rate,
latency) already come from `prometheus_fastapi_instrumentator` in main.py --
these are the metrics that instrumentator can't see: what happens *inside*
an agent run."""
from prometheus_client import Counter, Histogram

AGENT_STEPS = Histogram("agent_steps_total", "Number of LLM round-trips per agent run", buckets=(1, 2, 3, 4, 5))
AGENT_TOOL_CALLS = Counter("agent_tool_calls_total", "Total tool invocations across all agent runs", ["tool"])
AGENT_STOP_REASON = Counter("agent_stopped_reason_total", "Why an agent run ended", ["reason"])
AGENT_CITATIONS = Counter(
    "agent_citations_total", "Citations in final agent answers, by whether a tool result backs them", ["grounded"]
)
AGENT_UNSUPPORTED_IDENTIFIERS = Counter(
    "agent_unsupported_identifiers_total",
    "Code identifiers an answer attributes to a citation that the cited tool text does not contain",
)
AGENT_INJECTION_FLAGS = Counter(
    "agent_injection_flags_total", "Instruction-like sentences removed from tool results, by rule", ["rule"]
)
AGENT_AUDIT_WRITE_FAILURES = Counter("agent_audit_write_failures_total", "Audit log lines that could not be written")
CHAT_INJECTION_FLAGS = Counter(
    "chat_injection_flags_total", "Instruction-like sentences removed from /chat and /ws/chat context, by rule", ["rule"]
)
CHAT_CITATIONS = Counter(
    "chat_citations_total", "Citations in /chat and /ws/chat answers, by whether a retrieved chunk backs them", ["grounded"]
)
AGENT_CITATION_REPAIRS = Counter(
    "agent_citation_repairs_total",
    "Citation-repair turns, by whether the revised answer passed the checks",
    ["resolved"],
)
