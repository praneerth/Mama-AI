# Mama AI stable hand-gesture mode

This mode is designed for predictable Windows control on ordinary laptop
webcams. It is separate from the full experimental gesture profile system.

## Why it is faster

- The camera runs on a background thread.
- Only the newest frame is processed; stale frames are dropped.
- Live mouse movement uses the Windows User32 API instead of PyAutoGUI.
- Pointer control is relative, like a touchpad, so the cursor does not jump to
  a screen edge when the hand first appears.
- Pinch click uses hysteresis and a cooldown to prevent repeated clicks.
- Open palm explicitly arms control and a fist explicitly disarms it. Two
  fingers are reserved for scrolling and cannot toggle arming.

## Gestures

- Open palm held for about one second: arm
- Fist held for about one second: disarm
- Index finger: move pointer
- Thumb and index pinch: left click
- Index and middle fingers: scroll
- Ctrl+Alt+G: emergency stop

## Commands

From the repository root, run these files in order:

```cmd
SETUP_HAND_GESTURES.cmd
TEST_HAND_GESTURES.cmd
START_HAND_GESTURES.cmd
```

For the lowest latency after calibration:

```cmd
START_HAND_GESTURES_FAST.cmd
```

Fast mode has no camera preview. Stop it with Ctrl+C or run:

```cmd
STOP_HAND_GESTURES.cmd
```

## Environment

The launchers use a dedicated virtual environment beside the repository:

```text
C:\Users\hp\OneDrive\Desktop\Mama-AI-Gesture-Venv
```

Do not install EasyOCR, Ultralytics, `opencv-python`, or
`opencv-python-headless` in that environment. They belong in the main backend
virtual environment.
