import unittest

from app.gestures.safety import GestureSafetyController


class TestGestureSafety(unittest.TestCase):
    def test_starts_disarmed_and_toggles_with_cooldown(self) -> None:
        safety = GestureSafetyController(
            stale_frame_timeout_ms=500,
            arm_toggle_cooldown_ms=1000,
        )
        self.assertFalse(safety.actions_allowed)
        self.assertTrue(safety.toggle(1.0))
        self.assertTrue(safety.actions_allowed)
        self.assertFalse(safety.toggle(1.5))
        self.assertTrue(safety.armed)
        self.assertTrue(safety.toggle(2.1))
        self.assertFalse(safety.armed)

    def test_emergency_stop_is_latched(self) -> None:
        safety = GestureSafetyController()
        safety.toggle(1.0)
        safety.emergency_stop()
        self.assertFalse(safety.actions_allowed)
        self.assertFalse(safety.toggle(10.0))
        safety.reset_emergency()
        self.assertFalse(safety.emergency_latched)
        self.assertTrue(safety.toggle(11.0))

    def test_watchdog_disarms_after_stale_frame(self) -> None:
        safety = GestureSafetyController(
            stale_frame_timeout_ms=500,
            arm_toggle_cooldown_ms=1,
        )
        safety.observe_frame(1.0)
        safety.toggle(1.0)
        self.assertFalse(safety.watchdog_expired(1.4))
        self.assertTrue(safety.watchdog_expired(1.6))
        self.assertFalse(safety.armed)
