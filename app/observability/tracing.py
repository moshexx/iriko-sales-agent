"""
OpenTelemetry tracing setup — sends spans to SigNoz via OTLP/HTTP.

How tracing works:
  Every inbound request and agent run creates a "span" — a timed unit of work.
  Spans are nested: an HTTP request span contains the agent span, which contains
  LLM call spans. Together they form a "trace" you can inspect in SigNoz.

Why this matters:
  - "Why did this message take 12 seconds?" → look at the trace, find the slow LLM call
  - "Which tenant is slowest?" → filter traces by tenant_id
  - "Did the vector search fail?" → look at the retrieve node span

Setup:
  Call setup_tracing() once at app startup (see main.py lifespan).
  After that, all FastAPI requests are automatically instrumented.
  Add manual spans in the orchestrator for agent runs.

Environment:
  OTEL_EXPORTER_OTLP_ENDPOINT — SigNoz OTLP endpoint (e.g. https://signoz.simpliflow.me)
  OTEL_SERVICE_NAME           — service name shown in SigNoz (default: leadwise-api)
  APP_ENV                     — if "test", tracing is disabled (no external calls)
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# Module-level tracer — imported by other modules to create spans
tracer = None


def setup_tracing(app=None) -> None:
    """
    Initialize the OTel TracerProvider and optionally instrument FastAPI.

    Call this once during app startup. Safe to call in test environments —
    if APP_ENV=test or OTEL_EXPORTER_OTLP_ENDPOINT is not set, tracing is
    a no-op (uses the default NoopTracerProvider).

    Args:
        app: FastAPI app instance to instrument (optional).
    """
    global tracer

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    service_name = os.environ.get("OTEL_SERVICE_NAME", "leadwise-api")
    app_env = os.environ.get("APP_ENV", "development")

    # In tests or when no endpoint is configured, use the no-op provider.
    # This means no spans are exported but the API is still usable.
    if not endpoint or app_env == "test":
        from opentelemetry import trace
        tracer = trace.get_tracer(service_name)
        logger.info("tracing:noop app_env=%s endpoint=%r", app_env, endpoint)
        return

    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create({"service.name": service_name, "deployment.environment": app_env})
    provider = TracerProvider(resource=resource)

    exporter = OTLPSpanExporter(
        endpoint=f"{endpoint}/v1/traces",
        headers={"signoz-access-token": os.environ.get("OTEL_SIGNOZ_TOKEN", "")},
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    tracer = trace.get_tracer(service_name)

    # Auto-instrument FastAPI if app provided
    if app is not None:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app)

    logger.info("tracing:setup service=%s endpoint=%s", service_name, endpoint)


def get_tracer():
    """Return the module-level tracer (after setup_tracing() was called)."""
    global tracer
    if tracer is None:
        # Fallback: return a no-op tracer if setup wasn't called
        from opentelemetry import trace
        tracer = trace.get_tracer("leadwise")
    return tracer
