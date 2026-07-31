"""Validated operating-system action dispatch for gesture events."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.gestures.models import ActionCommand, ActionSpec, Gesture


class DesktopActionSink(Protocol):
    def screen_size(self) -> tuple[int, int]: ...
    def move(self, x: int, y: int) -> None: ...
    def click(self, button: str, clicks: int) -> None: ...
    def button_down(self, button: str) -> None: ...
    def button_up(self, button: str) -> None: ...
    def scroll(self, amount: int) -> None: ...
    def press(self, key: str) -> None: ...
    def hotkey(self, keys: tuple[str, ...]) -> None: ...


@dataclass
class RecordingActionSink:
    width: int = 1920
    height: int = 1080
    calls: list[tuple[str, tuple[Any, ...]]] = field(default_factory=list)

    def screen_size(self) -> tuple[int, int]:
        return self.width, self.height

    def move(self, x: int, y: int) -> None:
        self.calls.append(("move", (x, y)))

    def click(self, button: str, clicks: int) -> None:
        self.calls.append(("click", (button, clicks)))

    def button_down(self, button: str) -> None:
        self.calls.append(("button_down", (button,)))

    def button_up(self, button: str) -> None:
        self.calls.append(("button_up", (button,)))

    def scroll(self, amount: int) -> None:
        self.calls.append(("scroll", (amount,)))

    def press(self, key: str) -> None:
        self.calls.append(("press", (key,)))

    def hotkey(self, keys: tuple[str, ...]) -> None:
        self.calls.append(("hotkey", keys))


class PyAutoGUIActionSink:
    """Lazy native Windows sink; never imported by the backend container."""

    def __init__(self, pause_seconds: float = 0.0) -> None:
        try:
            import pyautogui
        except Exception as exc:
            raise RuntimeError(
                "Gesture desktop dependencies are unavailable. Install "
                "requirements-gesture.txt in the native Windows environment."
            ) from exc
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = pause_seconds
        self._pyautogui = pyautogui
        size = pyautogui.size()
        self._screen_size = (int(size.width), int(size.height))

    def screen_size(self) -> tuple[int, int]:
        return self._screen_size

    def move(self, x: int, y: int) -> None:
        self._pyautogui.moveTo(x, y, duration=0)

    def click(self, button: str, clicks: int) -> None:
        self._pyautogui.click(button=button, clicks=clicks, interval=0.10)

    def button_down(self, button: str) -> None:
        self._pyautogui.mouseDown(button=button)

    def button_up(self, button: str) -> None:
        self._pyautogui.mouseUp(button=button)

    def scroll(self, amount: int) -> None:
        self._pyautogui.scroll(amount)

    def press(self, key: str) -> None:
        self._pyautogui.press(key)

    def hotkey(self, keys: tuple[str, ...]) -> None:
        self._pyautogui.hotkey(*keys)


class ActionDispatcher:
    def __init__(self, sink: DesktopActionSink) -> None:
        self.sink = sink
        self.drag_button: str | None = None

    def release_all(self) -> None:
        if self.drag_button is not None:
            self.sink.button_up(self.drag_button)
            self.drag_button = None

    def dispatch(
        self,
        spec: ActionSpec,
        *,
        gesture: Gesture,
        profile: str,
        timestamp: float,
        dynamic: dict[str, Any] | None = None,
    ) -> ActionCommand:
        parameters = dict(spec.parameters)
        if dynamic:
            parameters.update(dynamic)
        action = spec.action
        if action == "noop":
            pass
        elif action == "mouse.move":
            self.sink.move(int(parameters["x"]), int(parameters["y"]))
        elif action == "mouse.click":
            self.sink.click(
                str(parameters.get("button", "left")),
                int(parameters.get("clicks", 1)),
            )
        elif action == "mouse.down":
            button = str(parameters.get("button", "left"))
            if self.drag_button is None:
                self.sink.button_down(button)
                self.drag_button = button
        elif action == "mouse.up":
            button = str(parameters.get("button", self.drag_button or "left"))
            if self.drag_button is not None:
                self.sink.button_up(button)
                self.drag_button = None
        elif action == "mouse.scroll":
            amount = int(parameters.get("amount", 0))
            if amount:
                self.sink.scroll(amount)
        elif action == "keyboard.press":
            self.sink.press(str(parameters["key"]).lower())
        elif action == "keyboard.hotkey":
            self.sink.hotkey(
                tuple(str(key).lower() for key in parameters["keys"])
            )
        else:
            raise ValueError(f"Unsupported action: {action}")
        return ActionCommand(
            action=action,
            parameters=parameters,
            gesture=gesture,
            profile=profile,
            timestamp=timestamp,
        )
