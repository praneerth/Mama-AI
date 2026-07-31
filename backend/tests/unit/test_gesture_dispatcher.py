import unittest

from app.gestures.dispatcher import ActionDispatcher, RecordingActionSink
from app.gestures.models import ActionSpec, Gesture


class TestGestureDispatcher(unittest.TestCase):
    def setUp(self) -> None:
        self.sink = RecordingActionSink()
        self.dispatcher = ActionDispatcher(self.sink)

    def dispatch(self, spec: ActionSpec, dynamic=None) -> None:
        self.dispatcher.dispatch(
            spec,
            gesture=Gesture.POINT,
            profile="test",
            timestamp=1.0,
            dynamic=dynamic,
        )

    def test_mouse_and_keyboard_actions(self) -> None:
        self.dispatch(ActionSpec("mouse.move"), {"x": 100, "y": 200})
        self.dispatch(ActionSpec("mouse.click", {"button": "left", "clicks": 2}))
        self.dispatch(ActionSpec("mouse.scroll"), {"amount": 3})
        self.dispatch(ActionSpec("keyboard.press", {"key": "space"}))
        self.dispatch(ActionSpec("keyboard.hotkey", {"keys": ["ctrl", "tab"]}))
        self.assertEqual(
            self.sink.calls,
            [
                ("move", (100, 200)),
                ("click", ("left", 2)),
                ("scroll", (3,)),
                ("press", ("space",)),
                ("hotkey", ("ctrl", "tab")),
            ],
        )

    def test_drag_is_idempotent_and_release_all_is_fail_safe(self) -> None:
        down = ActionSpec("mouse.down", {"button": "left"})
        self.dispatch(down)
        self.dispatch(down)
        self.assertEqual(self.sink.calls, [("button_down", ("left",))])
        self.dispatcher.release_all()
        self.assertEqual(self.sink.calls[-1], ("button_up", ("left",)))
        self.assertIsNone(self.dispatcher.drag_button)

    def test_noop_does_not_touch_desktop(self) -> None:
        command = self.dispatcher.dispatch(
            ActionSpec("noop"),
            gesture=Gesture.SWIPE_LEFT,
            profile="test",
            timestamp=1.0,
        )
        self.assertEqual(command.action, "noop")
        self.assertEqual(self.sink.calls, [])

    def test_unknown_action_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.dispatch(ActionSpec("process.start"))
