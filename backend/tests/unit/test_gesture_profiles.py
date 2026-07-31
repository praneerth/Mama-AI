import json
import tempfile
import unittest
from pathlib import Path

from app.gestures.models import Gesture
from app.gestures.profiles import ProfileRegistry, load_profile


class TestGestureProfiles(unittest.TestCase):
    def test_repository_profiles_load(self) -> None:
        directory = Path(__file__).resolve().parents[2] / "gesture_profiles"
        registry = ProfileRegistry.from_directory(directory)
        self.assertEqual(
            registry.names(),
            (
                "browser",
                "default",
                "offline_game",
                "presentation",
                "window_control",
            ),
        )
        self.assertEqual(
            registry.get("default").actions[Gesture.PINCH_INDEX].action,
            "mouse.click",
        )

    def test_active_window_selects_browser_and_presentation(self) -> None:
        directory = Path(__file__).resolve().parents[2] / "gesture_profiles"
        registry = ProfileRegistry.from_directory(directory)
        self.assertEqual(
            registry.resolve("default", "Docs - Google Chrome", auto_select=True).name,
            "browser",
        )
        self.assertEqual(
            registry.resolve("default", "Deck - PowerPoint", auto_select=True).name,
            "presentation",
        )
        self.assertEqual(
            registry.resolve("default", "Deck - PowerPoint", auto_select=False).name,
            "default",
        )

    def test_profile_rejects_shell_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.json"
            path.write_text(
                json.dumps(
                    {
                        "name": "bad",
                        "description": "bad",
                        "actions": {
                            "point": {
                                "action": "shell.run",
                                "parameters": {"command": "calc.exe"},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                load_profile(path)

    def test_profile_rejects_arbitrary_keyboard_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.json"
            path.write_text(
                json.dumps(
                    {
                        "name": "bad",
                        "description": "bad",
                        "actions": {
                            "swipe_up": {
                                "action": "keyboard.press",
                                "parameters": {"key": "launch-program"},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                load_profile(path)

    def test_duplicate_profile_names_are_rejected(self) -> None:
        payload = {
            "name": "same",
            "description": "same",
            "actions": {"point": {"action": "mouse.move"}},
        }
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "a.json").write_text(json.dumps(payload), encoding="utf-8")
            (directory / "b.json").write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(ValueError):
                ProfileRegistry.from_directory(directory)
