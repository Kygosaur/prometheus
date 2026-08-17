from __future__ import annotations

import json
import logging
import sys
import time
from contextvars import ContextVar

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

request_id_context: ContextVar[str] = ContextVar("request_id", default="-")
HTTP_REQUESTS = Counter("planning_http_requests_total", "HTTP requests", ["method", "route", "status"])
HTTP_DURATION = Histogram("planning_http_request_duration_seconds", "HTTP request time", ["method", "route"])
SOLVER_DURATION = Histogram("planning_solver_duration_seconds", "OR-Tools solve time")
ACTIVE_REQUESTS = Gauge("planning_http_active_requests", "Requests currently executing")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({"timestamp": self.formatTime(record), "level": record.levelname, "logger": record.name, "message": record.getMessage(), "request_id": request_id_context.get()}, default=str)


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.getLogger().handlers = [handler]
    logging.getLogger().setLevel(logging.INFO)


def install_observability(app: FastAPI, otlp_endpoint: str | None = None) -> None:
    configure_logging()

    @app.middleware("http")
    async def prometheus_middleware(request: Request, call_next):
        ACTIVE_REQUESTS.inc()
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            route = request.scope.get("route")
            route_name = getattr(route, "path", request.url.path)
            HTTP_REQUESTS.labels(request.method, route_name, str(status)).inc()
            HTTP_DURATION.labels(request.method, route_name).observe(time.perf_counter() - started)
            ACTIVE_REQUESTS.dec()

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    if otlp_endpoint:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        provider = TracerProvider(resource=Resource.create({"service.name": "prometheus-planning-api"}))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)))
        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument_app(app)
