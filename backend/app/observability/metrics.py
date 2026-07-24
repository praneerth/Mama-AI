"""Dependency-free Prometheus metrics registry for Mama AI."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from threading import RLock
from typing import Any


_METRIC_NAME = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")
_LABEL_NAME = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _escape_label(value: object) -> str:
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace('"', '\\"')
    )


def _format_number(value: float) -> str:
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "+Inf" if value > 0 else "-Inf"
    if value.is_integer():
        return str(int(value))
    return format(value, ".12g")


class MetricsRegistry:
    """Thread-safe counters, gauges, and summary observations."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._types: dict[str, str] = {}
        self._help: dict[str, str] = {}
        self._counters: defaultdict[tuple[str, tuple], float] = defaultdict(float)
        self._gauges: dict[tuple[str, tuple], float] = {}
        self._summaries: defaultdict[tuple[str, tuple], dict[str, float]] = defaultdict(
            lambda: {"count": 0.0, "sum": 0.0, "max": 0.0}
        )

    @staticmethod
    def _labels(labels: dict[str, object] | None) -> tuple[tuple[str, str], ...]:
        normalized: list[tuple[str, str]] = []
        for key, value in sorted((labels or {}).items()):
            if not _LABEL_NAME.fullmatch(str(key)):
                raise ValueError(f"Invalid metric label name: {key}")
            normalized.append((str(key), str(value)))
        return tuple(normalized)

    def _register(self, name: str, metric_type: str, help_text: str) -> None:
        if not _METRIC_NAME.fullmatch(name):
            raise ValueError(f"Invalid metric name: {name}")
        current = self._types.get(name)
        if current is not None and current != metric_type:
            raise ValueError(f"Metric {name} is already registered as {current}.")
        self._types[name] = metric_type
        self._help.setdefault(name, help_text.strip() or name)

    def increment(
        self,
        name: str,
        amount: float = 1.0,
        *,
        labels: dict[str, object] | None = None,
        help_text: str = "Counter metric.",
    ) -> None:
        amount = float(amount)
        if amount < 0:
            raise ValueError("Counter increments cannot be negative.")
        label_key = self._labels(labels)
        with self._lock:
            self._register(name, "counter", help_text)
            self._counters[(name, label_key)] += amount

    def set_gauge(
        self,
        name: str,
        value: float,
        *,
        labels: dict[str, object] | None = None,
        help_text: str = "Gauge metric.",
    ) -> None:
        label_key = self._labels(labels)
        with self._lock:
            self._register(name, "gauge", help_text)
            self._gauges[(name, label_key)] = float(value)

    def observe(
        self,
        name: str,
        value: float,
        *,
        labels: dict[str, object] | None = None,
        help_text: str = "Summary metric.",
    ) -> None:
        value = float(value)
        if value < 0:
            raise ValueError("Metric observations cannot be negative.")
        label_key = self._labels(labels)
        with self._lock:
            self._register(name, "summary", help_text)
            item = self._summaries[(name, label_key)]
            item["count"] += 1
            item["sum"] += value
            item["max"] = max(item["max"], value)

    def counter_total(
        self,
        name: str,
        *,
        labels: dict[str, object] | None = None,
    ) -> float:
        expected = dict(self._labels(labels))
        with self._lock:
            total = 0.0
            for (metric_name, label_key), value in self._counters.items():
                if metric_name != name:
                    continue
                actual = dict(label_key)
                if all(actual.get(key) == val for key, val in expected.items()):
                    total += value
            return total

    def gauge_value(
        self,
        name: str,
        *,
        labels: dict[str, object] | None = None,
        default: float = 0.0,
    ) -> float:
        label_key = self._labels(labels)
        with self._lock:
            return self._gauges.get((name, label_key), float(default))

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            counters = [
                {"name": name, "labels": dict(labels), "value": value}
                for (name, labels), value in sorted(self._counters.items())
            ]
            gauges = [
                {"name": name, "labels": dict(labels), "value": value}
                for (name, labels), value in sorted(self._gauges.items())
            ]
            summaries = [
                {"name": name, "labels": dict(labels), **dict(value)}
                for (name, labels), value in sorted(self._summaries.items())
            ]
        return {
            "counters": counters,
            "gauges": gauges,
            "summaries": summaries,
        }

    def render_prometheus(self) -> str:
        with self._lock:
            lines: list[str] = []
            for name in sorted(self._types):
                metric_type = self._types[name]
                lines.append(f"# HELP {name} {self._help[name]}")
                lines.append(f"# TYPE {name} {metric_type}")
                if metric_type == "counter":
                    values = [
                        (labels, value)
                        for (metric_name, labels), value in self._counters.items()
                        if metric_name == name
                    ]
                    for labels, value in sorted(values):
                        lines.append(self._sample(name, labels, value))
                elif metric_type == "gauge":
                    values = [
                        (labels, value)
                        for (metric_name, labels), value in self._gauges.items()
                        if metric_name == name
                    ]
                    for labels, value in sorted(values):
                        lines.append(self._sample(name, labels, value))
                else:
                    values = [
                        (labels, value)
                        for (metric_name, labels), value in self._summaries.items()
                        if metric_name == name
                    ]
                    for labels, value in sorted(values):
                        lines.append(self._sample(name + "_count", labels, value["count"]))
                        lines.append(self._sample(name + "_sum", labels, value["sum"]))
                        lines.append(self._sample(name + "_max", labels, value["max"]))
            return "\n".join(lines) + ("\n" if lines else "")

    @staticmethod
    def _sample(name: str, labels: tuple[tuple[str, str], ...], value: float) -> str:
        rendered_labels = ""
        if labels:
            rendered_labels = "{" + ",".join(
                f'{key}="{_escape_label(label_value)}"'
                for key, label_value in labels
            ) + "}"
        return f"{name}{rendered_labels} {_format_number(float(value))}"

    def reset(self) -> None:
        with self._lock:
            self._types.clear()
            self._help.clear()
            self._counters.clear()
            self._gauges.clear()
            self._summaries.clear()


metrics_registry = MetricsRegistry()


__all__ = ["MetricsRegistry", "metrics_registry"]
