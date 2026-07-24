"""Operational alert evaluation for Mama AI."""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.observability.metrics import metrics_registry


def evaluate_alerts(runtime: dict[str, Any]) -> dict[str, Any]:
    alerts: list[dict[str, Any]] = []
    total = metrics_registry.counter_total("mama_ai_http_requests_total")
    server_errors = metrics_registry.counter_total(
        "mama_ai_http_errors_total",
        labels={"category": "server"},
    )
    error_rate = (server_errors / total * 100.0) if total else 0.0

    if not runtime["database"]["available"]:
        alerts.append({
            "code": "database_unavailable",
            "severity": "critical",
            "message": "The runtime database probe is failing.",
        })
    if runtime["runtime_started"] and not runtime["worker_running"]:
        alerts.append({
            "code": "worker_not_running",
            "severity": "critical",
            "message": "The runtime is started but the durable worker is stopped.",
        })
    failed_jobs = int(runtime["queue"]["counts"].get("failed", 0))
    if failed_jobs >= settings.OBSERVABILITY_ALERT_FAILED_QUEUE_JOBS:
        alerts.append({
            "code": "failed_queue_jobs",
            "severity": "warning",
            "message": "Failed durable queue jobs reached the alert threshold.",
            "value": failed_jobs,
            "threshold": settings.OBSERVABILITY_ALERT_FAILED_QUEUE_JOBS,
        })
    stale_claimed = int(runtime["queue"]["stale_claimed"])
    if stale_claimed >= settings.OBSERVABILITY_ALERT_STALE_CLAIMS:
        alerts.append({
            "code": "stale_queue_claims",
            "severity": "warning",
            "message": "Expired durable queue leases reached the alert threshold.",
            "value": stale_claimed,
            "threshold": settings.OBSERVABILITY_ALERT_STALE_CLAIMS,
        })
    if total >= settings.OBSERVABILITY_ALERT_MIN_REQUESTS and error_rate >= settings.OBSERVABILITY_ALERT_ERROR_RATE_PERCENT:
        alerts.append({
            "code": "http_error_rate",
            "severity": "warning",
            "message": "HTTP server error rate reached the alert threshold.",
            "value_percent": round(error_rate, 3),
            "threshold_percent": settings.OBSERVABILITY_ALERT_ERROR_RATE_PERCENT,
        })

    severity_order = {"warning": 1, "critical": 2}
    highest = max((severity_order[item["severity"]] for item in alerts), default=0)
    status = "critical" if highest == 2 else "degraded" if highest == 1 else "healthy"
    return {
        "status": status,
        "alert_count": len(alerts),
        "alerts": alerts,
        "request_sample": {
            "total": int(total),
            "server_errors": int(server_errors),
            "server_error_rate_percent": round(error_rate, 3),
        },
    }


__all__ = ["evaluate_alerts"]
