import os
import unittest
from pathlib import Path
from unittest.mock import patch

from app.gestures.config import GestureAgentConfig


class TestGestureConfig(unittest.TestCase):
    def test_defaults_are_safe(self) -> None:
        config = GestureAgentConfig()
        self.assertEqual(config.maximum_hands, 1)
        self.assertFalse(config.dry_run)
        self.assertGreaterEqual(config.arm_hold_ms, 1000)
        self.assertTrue(config.preview_enabled)

    def test_environment_configuration(self) -> None:
        environment = {
            "MAMA_GESTURE_CAMERA_INDEX": "2",
            "MAMA_GESTURE_PROFILE": "browser",
            "MAMA_GESTURE_PREVIEW": "false",
            "MAMA_GESTURE_DRY_RUN": "true",
            "MAMA_GESTURE_PROFILES_DIR": "gesture_profiles",
        }
        with patch.dict(os.environ, environment, clear=False):
            config = GestureAgentConfig.from_environment()
        self.assertEqual(config.camera_index, 2)
        self.assertEqual(config.profile_name, "browser")
        self.assertFalse(config.preview_enabled)
        self.assertTrue(config.dry_run)
        self.assertTrue(config.profiles_directory.is_absolute())

    def test_invalid_values_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            GestureAgentConfig(maximum_hands=2)
        with self.assertRaises(ValueError):
            GestureAgentConfig(minimum_frame_confidence=0)
        with self.assertRaises(ValueError):
            GestureAgentConfig(cursor_margin=0.5)
        with self.assertRaises(ValueError):
            GestureAgentConfig(profiles_directory=Path("."), arm_hold_ms=0)
