import unittest

from app.observability.metrics import MetricsRegistry


class TestObservabilityMetrics(unittest.TestCase):
    def setUp(self):
        self.registry = MetricsRegistry()

    def test_counter_accumulates(self):
        self.registry.increment("mama_test_total", labels={"kind": "ok"})
        self.registry.increment("mama_test_total", 2, labels={"kind": "ok"})
        self.assertEqual(
            self.registry.counter_total("mama_test_total", labels={"kind": "ok"}),
            3,
        )

    def test_counter_rejects_negative_increment(self):
        with self.assertRaises(ValueError):
            self.registry.increment("mama_test_total", -1)

    def test_gauge_replaces_value(self):
        self.registry.set_gauge("mama_worker", 0)
        self.registry.set_gauge("mama_worker", 1)
        self.assertEqual(self.registry.gauge_value("mama_worker"), 1)

    def test_summary_tracks_count_sum_and_max(self):
        self.registry.observe("mama_duration_seconds", 0.25)
        self.registry.observe("mama_duration_seconds", 0.75)
        summary = self.registry.snapshot()["summaries"][0]
        self.assertEqual(summary["count"], 2)
        self.assertEqual(summary["sum"], 1)
        self.assertEqual(summary["max"], 0.75)

    def test_metric_type_cannot_change(self):
        self.registry.increment("mama_conflict_total")
        with self.assertRaises(ValueError):
            self.registry.set_gauge("mama_conflict_total", 1)

    def test_invalid_metric_name_is_rejected(self):
        with self.assertRaises(ValueError):
            self.registry.increment("invalid metric")

    def test_prometheus_output_contains_help_type_and_labels(self):
        self.registry.increment(
            "mama_requests_total",
            labels={"route": '/chat"one'},
            help_text="Request count.",
        )
        output = self.registry.render_prometheus()
        self.assertIn("# HELP mama_requests_total Request count.", output)
        self.assertIn("# TYPE mama_requests_total counter", output)
        self.assertIn('route="/chat\\"one"', output)

    def test_reset_clears_all_metrics(self):
        self.registry.increment("mama_reset_total")
        self.registry.reset()
        self.assertEqual(self.registry.snapshot()["counters"], [])
        self.assertEqual(self.registry.render_prometheus(), "")


if __name__ == "__main__":
    unittest.main()
