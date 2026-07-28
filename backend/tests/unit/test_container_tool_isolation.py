from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from app.commands.router import process_command
from app.tools.manager import execute_tool


class TestContainerToolIsolation(unittest.TestCase):
    def test_click_fails_safely_without_importing_pyautogui(self):
        original = sys.modules.pop("pyautogui", None)
        try:
            with patch("app.tools.manager.settings.CONTAINER_MODE", True):
                result = execute_tool("click 10 20")
            self.assertTrue(result.startswith("ERROR:"))
            self.assertIn("container mode", result.lower())
            self.assertNotIn("pyautogui", sys.modules)
        finally:
            if original is not None:
                sys.modules["pyautogui"] = original

    def test_command_router_fails_safely_in_container_mode(self):
        with patch("app.commands.router.settings.CONTAINER_MODE", True):
            result = process_command("open notepad")
        self.assertTrue(result.startswith("ERROR:"))
        self.assertIn("native mama ai desktop agent", result.lower())


if __name__ == "__main__":
    unittest.main()
