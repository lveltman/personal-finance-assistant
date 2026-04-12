"""Prometheus metrics definitions — import this module to register all metrics."""
from prometheus_client import Counter, Gauge, Histogram

# ---------------------------------------------------------------------------
# Latency
# ---------------------------------------------------------------------------

request_duration = Histogram(
    "pfa_request_duration_seconds",
    "End-to-end request latency",
    ["status"],  # success | error
)

tool_call_duration = Histogram(
    "pfa_tool_call_duration_seconds",
    "Tool execution latency",
    ["tool_name"],
)

llm_call_duration = Histogram(
    "pfa_llm_call_duration_seconds",
    "LLM inference latency",
    ["model"],
)

# ---------------------------------------------------------------------------
# Throughput
# ---------------------------------------------------------------------------

requests_total = Counter(
    "pfa_requests_total",
    "Total processed requests",
    ["status"],  # success | error | blocked
)

tool_calls_total = Counter(
    "pfa_tool_calls_total",
    "Total tool invocations",
    ["tool_name", "status"],  # status: success | error
)

active_requests = Gauge(
    "pfa_active_requests",
    "Requests currently being processed",
)

# ---------------------------------------------------------------------------
# LLM cost / quality
# ---------------------------------------------------------------------------

llm_tokens_total = Counter(
    "pfa_llm_tokens_total",
    "LLM tokens consumed",
    ["model", "type"],  # type: input | output
)

fallback_total = Counter(
    "pfa_fallback_total",
    "LLM fallback activations",
    ["reason"],  # timeout | error
)

# ---------------------------------------------------------------------------
# Reliability / guard
# ---------------------------------------------------------------------------

errors_total = Counter(
    "pfa_errors_total",
    "Errors by component",
    ["component"],  # orchestrator | tool | llm | file_parser
)

guardrail_blocked_total = Counter(
    "pfa_guardrail_blocked_total",
    "Requests blocked by pre-flight guard",
    ["reason"],  # rate_limit | out_of_domain | file_too_large
)

# ---------------------------------------------------------------------------
# Categorizer
# ---------------------------------------------------------------------------

categorization_total = Counter(
    "pfa_categorization_total",
    "Categorization attempts by method",
    ["method"],  # rules | embedding | llm | fallback
)
