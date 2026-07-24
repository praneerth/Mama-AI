"""Privileged Prometheus metrics and operational diagnostics API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

from app.api.auth import require_runtime_reader
from app.config import settings
from app.observability.alerts import evaluate_alerts
from app.observability.metrics import metrics_registry
from app.observability.runtime import collect_runtime_metrics


router = APIRouter(
    tags=["Observability"],
    dependencies=[Depends(require_runtime_reader)],
)


@router.get("/metrics", response_class=PlainTextResponse)
def prometheus_metrics() -> PlainTextResponse:
    """Return Prometheus-compatible metrics to an operational reader."""

    if not settings.METRICS_ENABLED:
        return PlainTextResponse(
            "# Mama AI metrics are disabled.\n",
            status_code=503,
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )
    collect_runtime_metrics()
    return PlainTextResponse(
        metrics_registry.render_prometheus(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@router.get("/health/observability")
def observability_health() -> dict[str, Any]:
    """Return redacted operational metrics and evaluated alerts."""

    runtime = collect_runtime_metrics()
    alert_report = evaluate_alerts(runtime)
    return {
        "status": alert_report["status"],
        "enabled": settings.OBSERVABILITY_ENABLED,
        "metrics_enabled": settings.METRICS_ENABLED,
        "runtime": runtime,
        "alerts": alert_report,
        "metrics": metrics_registry.snapshot(),
    }


__all__ = [
    "observability_health",
    "prometheus_metrics",
    "router",
]
