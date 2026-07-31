# Mama AI Hand Gestures — Windows Phase 1

This package adds a native, local-only Windows hand-gesture agent. It does not
run inside the production backend container and does not send webcam frames to
the backend or an external service.

## Safety model

Gesture control starts disarmed. Hold the index, middle, and ring fingers up
for the configured arm duration to toggle control. `Ctrl+Alt+G` immediately
latches an emergency stop. Moving the mouse to the top-left corner also retains
PyAutoGUI's native fail-safe. A valid-hand watchdog disarms the agent and
releases any held mouse button when tracking stops.

Only one hand is accepted in Phase 1. Actions use a strict allowlist; profile
JSON cannot run programs, shell commands, arbitrary text, or arbitrary key
names. The offline-game profile is manual opt-in and should only be used with
offline or explicitly permitted games. The project does not bypass anti-cheat
or application security controls.

## Included gestures

| Gesture | Default behaviour |
| --- | --- |
| Index finger | Move the cursor |
| Thumb/index pinch | Left click |
| Thumb/middle pinch | Right click |
| Thumb/ring pinch | Double click |
| Index and middle fingers | Scroll vertically |
| Closed fist | Hold the left mouse button for drag |
| Open palm | Release drag; enables swipe tracking in mapped profiles |
| Three fingers | Arm or disarm after a hold |
| Open-palm swipe | Profile-specific browser, presentation, or game key |

## Install on Windows

From `backend` with the existing virtual environment active:

```cmd
python -m pip install -r requirements-gesture.txt
```

Phase 1 pins MediaPipe to `0.10.21` because MediaPipe `0.10.30` and later removed the legacy `mp.solutions` API used by this adapter. Verify the installation with:

```cmd
python -c "import mediapipe as mp; print(mp.__version__); print(hasattr(mp, 'solutions'))"
```

The expected output is `0.10.21` followed by `True`.

The tested Windows dependency set uses NumPy `1.26.4` and
`opencv-contrib-python` `4.11.0.86`. Install only that OpenCV wheel. The four
OpenCV wheel variants share the same `cv2` namespace, so installing standard,
headless, and contrib variants together can leave the environment inconsistent.
When cleaning an older environment, remove all OpenCV wheel variants before
reinstalling `requirements-gesture.txt`.

The core tests do not require OpenCV, MediaPipe, a camera, or a desktop session.
The native agent does require all three packages in `requirements-gesture.txt`.

## First run: dry-run mode

Run from the repository root:

```cmd
python scripts\hand_gesture_agent.py --dry-run
```

Dry-run mode opens the camera and performs recognition but records actions
instead of moving the mouse or pressing keys. Press `Q`, `Esc`, or `Ctrl+C` to
exit.

## Live desktop run

```cmd
python scripts\hand_gesture_agent.py --profile default
```

Hold three fingers to arm. Start with the `default` profile. Browser and
presentation profiles can be selected automatically from the active window
title. Automatic selection can be disabled:

```cmd
python scripts\hand_gesture_agent.py --profile default --no-auto-profile
```

The offline game mapping must be selected explicitly:

```cmd
python scripts\hand_gesture_agent.py --profile offline_game
```

## Configuration

Environment variables are documented in `.env.example`. Important controls:

- `MAMA_GESTURE_CAMERA_INDEX`
- `MAMA_GESTURE_PROFILE`
- `MAMA_GESTURE_PREVIEW`
- `MAMA_GESTURE_ARM_HOLD_MS`
- `MAMA_GESTURE_STALE_FRAME_TIMEOUT_MS`
- `MAMA_GESTURE_DRY_RUN`
- `MAMA_GESTURE_AUTO_SELECT_PROFILES`

## Phase 1 boundaries

This is the gesture-engine foundation. It does not yet include a polished
system-tray UI, calibration wizard, signed desktop installer, mobile camera
input, accessibility certification, or broad real-device compatibility data.
Those are later gesture and desktop phases.

## Stability and low-latency defaults

The native agent requests a 640×480, 30 FPS camera stream, keeps the capture
buffer at one frame, and uses MediaPipe model complexity `0`. This reduces old
buffered frames and CPU load. The active-window title is polled four times per
second instead of on every camera frame, and the PyAutoGUI screen size is
cached.

Gesture labels pass through a temporal stabilizer. A new pose must be observed
for three matching frames before it becomes active, while two empty frames are
required to release it. This prevents one-frame landmark flicker from changing
a click into a scroll or interrupting a continuous gesture.

After the three-finger pose toggles arming, it must be released for at least
`MAMA_GESTURE_ARM_RELEASE_MS` before it can toggle again. Brief recognition
flicker therefore cannot immediately disarm the controller.

For normal scrolling, keep `MAMA_GESTURE_SCROLL_DEAD_ZONE` close to `0.010`.
Values such as `0.060` require very large movement between consecutive frames
and can make scrolling appear delayed or inactive.
