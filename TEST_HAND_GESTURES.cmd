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
echo Mama AI Gesture Recognition Test V7.1
echo Safe mode: the mouse and browser cannot be controlled.
echo.
echo This restores the smooth classic finger tracking with only the index dot.
echo Open palm: hold until ARMED, then move the same open palm left or right.
echo No lowering hand and no index-finger preparation are required.
echo.
echo I = thumb-to-index distance
echo M = thumb-to-middle distance
echo R = thumb-to-ring distance
echo.
"%PYTHON%" scripts\hand_gesture_stable.py --dry-run --camera 0
pause
