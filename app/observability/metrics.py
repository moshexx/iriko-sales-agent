"""
Custom OpenTelemetry metrics — counters and histograms for key business events.

Metrics exported to SigNoz → visible in dashboards.

Key metrics:
  messages_received_total    — every webhook received (by tenant, graph_type)
  messages_accepted_total    — messages that passed filtering and dedup
  messages_rejected_total    — filtered/deduped/rate-limited messages (by reason)
  agent_runs_total           — completed agent executions (by tenant, qualification)
  agent_duration_seconds     — histogram of agent run latency
  dlq_events_total           — messages that failed and landed in DLQ

Usage:
    from app.observability.metrics import record_message_received, record_agent_run
    record_message_received(tenant_id="...", accepted=True)
    record_agent_run(tenant_id="...", graph_type="iroko", duration_seconds=3.2)
"""

from __future__ import annotations

import time
from contextlib import contextmanager

# ─── Lazy initialization ──────────────────────────────────────────────────────

_meter = None
_counters: dict = {}
_histograms: dict = {}


def _get_meter():
    global _meter
    if _meter is None:
        from opentelemetry import metrics
        _meter = metrics.get_meter("leadwise", version="0.1.0")
    return _meter


def _counter(name: str, description: str):
    if name not in _counters:
        _counters[name] = _get_meter().create_counter(name, description=description)
    return _counters[name]


def _histogram(name: str, description: str, unit: str = "s"):
    if name not in _histograms:
        _histograms[name] = _get_meter().create_histogram(
            name, description=description, unit=unit
        )
    return _histograms[name]


# ─── Public API ───────────────────────────────────────────────────────────────

def record_message_received(*, tenant_id: str, instance_id: str) -> None:
    """Call when a webhook arrives (before any filtering)."""
    _counter(
        "leadwise.messages.received",
        "Total webhooks received from Green API",
    ).add(1, {"tenant_id": tenant_id, "instance_id": instance_id})


def record_message_accepted(*, tenant_id: str, graph_type: str) -> None:
    """Call when a message passes all filters and is dispatched to ARQ."""
    _counter(
        "leadwise.messages.accepted",
        "Messages accepted and dispatched to the agent queue",
    ).add(1, {"tenant_id": tenant_id, "graph_type": graph_type})


def record_message_rejected(*, tenant_id: str, reason: str) -> None:
    """
    Call when a message is rejected.
    reason: outgoing, group, empty_text, duplicate, rate_limited, tenant_not_found, parse_error
    """
    _counter(
        "leadwise.messages.rejected",
        "Messages rejected before reaching the agent",
    ).add(1, {"tenant_id": tenant_id, "reason": reason})


def record_agent_run(
    *,
    tenant_id: str,
    graph_type: str,
    qualification: str,
    duration_seconds: float,
) -> None:
    """Call after a successful agent run."""
    labels = {"tenant_id": tenant_id, "graph_type": graph_type, "qualification": qualification}
    _counter("leadwise.agent.runs", "Completed agent executions").add(1, labels)
    _histogram(
        "leadwise.agent.duration",
        "Agent run duration in seconds",
        unit="s",
    ).record(duration_seconds, {"tenant_id": tenant_id, "graph_type": graph_type})


def record_dlq_event(*, tenant_id: str, graph_type: str, attempt: int) -> None:
    """Call when a message fails and is saved to the DLQ."""
    _counter(
        "leadwise.dlq.events",
        "Messages that failed processing and landed in the DLQ",
    ).add(1, {"tenant_id": tenant_id, "graph_type": graph_type, "attempt": str(attempt)})


@contextmanager
def timer():
    """Context manager that yields and returns elapsed seconds."""
    start = time.monotonic()
    try:
        yield
    finally:
        elapsed = time.monotonic() - start
        # Caller reads elapsed via the context manager's value
        # Usage: with timer() as t: ... then t.elapsed
        pass


class Timer:
    """Simple timer for measuring agent run duration."""
    def __init__(self):
        self._start = time.monotonic()

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._start
