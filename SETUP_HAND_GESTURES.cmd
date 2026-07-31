@echo off
setlocal
set "ROOT=%~dp0"
set "GESTURE_VENV=%ROOT%..\Mama-AI-Gesture-Venv"

cd /d "%ROOT%"
echo [1/4] Creating the dedicated gesture environment...
if not exist "%GESTURE_VENV%\Scripts\python.exe" (
    py -3.10 -m venv "%GESTURE_VENV%"
    if errorlevel 1 goto :failed
)

call "%GESTURE_VENV%\Scripts\activate.bat"
echo [2/4] Removing conflicting OpenCV wheels...
python -m pip uninstall -y opencv-python opencv-python-headless opencv-contrib-python-headless >nul 2>&1

echo [3/4] Installing the tested gesture dependencies...
python -m pip install --upgrade pip
if errorlevel 1 goto :failed
python -m pip install --upgrade --force-reinstall -r backend\requirements-gesture.txt
if errorlevel 1 goto :failed

echo [4/4] Verifying the environment...
python -m pip check
if errorlevel 1 goto :failed
python -c "import cv2, mediapipe as mp, numpy as np; print('OpenCV:', cv2.__version__); print('MediaPipe:', mp.__version__); print('NumPy:', np.__version__); print('Solutions:', hasattr(mp, 'solutions'))"
if errorlevel 1 goto :failed

echo.
echo Gesture setup completed successfully.
echo Next run TEST_HAND_GESTURES.cmd
pause
exit /b 0

:failed
echo.
echo Gesture setup failed. Read the error above.
pause
exit /b 1
