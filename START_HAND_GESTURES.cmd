@echo off
setlocal
set "ROOT=%~dp0"
set "PYTHON=%ROOT%..\Mama-AI-Gesture-Venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo Gesture environment not found. Run SETUP_HAND_GESTURES.cmd first.
    pause
    exit /b 1
)
cd /d "%ROOT%"
echo Mama AI Stable Gestures V7.1 - Classic Finger + Simple Palm
echo.
echo Open palm for about half a second = activate
echo Keep palm open and move left = browser back
echo Keep palm open and move right = browser forward
echo No lowering hand or index preparation is required
echo Closed fist for 1 second = deactivate
echo Index finger only = move pointer
echo Quick thumb + index pinch = left click
echo Hold thumb + index pinch = drag; release = drop
echo Thumb + middle pinch = right click
echo Thumb + ring pinch = double click
echo Index + middle fingers = scroll
echo Ctrl+Alt+G = emergency stop
echo Q or Esc = close
echo.
"%PYTHON%" scripts\hand_gesture_stable.py --camera 0
pause
