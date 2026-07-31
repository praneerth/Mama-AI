"""Strict gesture-profile loading and active-window resolution."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from app.gestures.models import ActionSpec, Gesture, GestureProfile


_ALLOWED_ACTIONS = {
    "noop",
    "mouse.move",
    "mouse.click",
    "mouse.down",
    "mouse.up",
    "mouse.scroll",
    "keyboard.press",
    "keyboard.hotkey",
}
_ALLOWED_BUTTONS = {"left", "middle", "right"}
_ALLOWED_KEYS = {
    "alt",
    "backspace",
    "ctrl",
    "delete",
    "down",
    "end",
    "enter",
    "esc",
    "home",
    "left",
    "pagedown",
    "pageup",
    "right",
    "shift",
    "space",
    "tab",
    "up",
}


def _validate_parameters(action: str, parameters: Mapping[str, Any]) -> None:
    if action in {"mouse.click", "mouse.down", "mouse.up"}:
        button = str(parameters.get("button", "left")).lower()
        if button not in _ALLOWED_BUTTONS:
            raise ValueError(f"Unsupported mouse button: {button}")
    if action == "mouse.click":
        clicks = int(parameters.get("clicks", 1))
        if clicks not in {1, 2}:
            raise ValueError("mouse.click supports one or two clicks.")
    if action == "keyboard.press":
        key = str(parameters.get("key", "")).lower()
        if key not in _ALLOWED_KEYS:
            raise ValueError(f"Unsupported keyboard key: {key}")
    if action == "keyboard.hotkey":
        keys = parameters.get("keys")
        if not isinstance(keys, list) or not 1 <= len(keys) <= 4:
            raise ValueError("keyboard.hotkey requires one to four keys.")
        invalid = [str(key).lower() for key in keys if str(key).lower() not in _ALLOWED_KEYS]
        if invalid:
            raise ValueError(f"Unsupported hotkey keys: {', '.join(invalid)}")


def load_profile(path: Path) -> GestureProfile:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Gesture profile must be a JSON object.")
    name = str(payload.get("name", "")).strip()
    description = str(payload.get("description", "")).strip()
    actions_payload = payload.get("actions")
    if not isinstance(actions_payload, dict):
        raise ValueError("Gesture profile actions must be an object.")
    actions: dict[Gesture, ActionSpec] = {}
    for gesture_name, raw_spec in actions_payload.items():
        try:
            gesture = Gesture(str(gesture_name).lower())
        except ValueError as exc:
            raise ValueError(f"Unsupported gesture: {gesture_name}") from exc
        if not isinstance(raw_spec, dict):
            raise ValueError(f"Action for {gesture.value} must be an object.")
        action = str(raw_spec.get("action", "")).strip().lower()
        if action not in _ALLOWED_ACTIONS:
            raise ValueError(f"Unsupported action: {action}")
        parameters = raw_spec.get("parameters", {})
        if not isinstance(parameters, dict):
            raise ValueError("Action parameters must be an object.")
        _validate_parameters(action, parameters)
        actions[gesture] = ActionSpec(
            action=action,
            parameters=dict(parameters),
            dwell_ms=int(raw_spec.get("dwell_ms", 120)),
            cooldown_ms=int(raw_spec.get("cooldown_ms", 350)),
        )
    patterns = payload.get("window_title_patterns", [])
    if not isinstance(patterns, list) or not all(isinstance(item, str) for item in patterns):
        raise ValueError("window_title_patterns must be a list of strings.")
    for pattern in patterns:
        re.compile(pattern, re.IGNORECASE)
    return GestureProfile(
        name=name,
        description=description,
        actions=actions,
        window_title_patterns=tuple(patterns),
        auto_select=bool(payload.get("auto_select", False)),
        priority=int(payload.get("priority", 0)),
    )


class ProfileRegistry:
    def __init__(self, profiles: Mapping[str, GestureProfile]) -> None:
        if not profiles:
            raise ValueError("At least one gesture profile is required.")
        self._profiles = dict(profiles)

    @classmethod
    def from_directory(cls, directory: Path) -> "ProfileRegistry":
        profiles: dict[str, GestureProfile] = {}
        for path in sorted(directory.glob("*.json")):
            profile = load_profile(path)
            if profile.name in profiles:
                raise ValueError(f"Duplicate gesture profile: {profile.name}")
            profiles[profile.name] = profile
        return cls(profiles)

    def get(self, name: str) -> GestureProfile:
        try:
            return self._profiles[name]
        except KeyError as exc:
            raise KeyError(f"Unknown gesture profile: {name}") from exc

    def resolve(
        self,
        default_name: str,
        window_title: str,
        *,
        auto_select: bool,
    ) -> GestureProfile:
        default = self.get(default_name)
        if not auto_select or not window_title:
            return default
        matches: list[GestureProfile] = []
        for profile in self._profiles.values():
            if not profile.auto_select:
                continue
            if any(
                re.search(pattern, window_title, re.IGNORECASE)
                for pattern in profile.window_title_patterns
            ):
                matches.append(profile)
        if not matches:
            return default
        return max(matches, key=lambda profile: profile.priority)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._profiles))
