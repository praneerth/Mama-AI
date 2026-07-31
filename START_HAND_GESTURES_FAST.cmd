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
echo Fast mode has no camera preview. Press Ctrl+C to close it.
echo Ctrl+Alt+G is the emergency stop.
"%PYTHON%" scripts\hand_gesture_stable.py --camera 0 --no-preview
pause
