@echo off
chcp 65001 >nul 2>&1
echo.
echo ==========================================
echo   MOZA RACING US Price Monitor
echo   Starting Backend Server...
echo ==========================================
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found.
    pause
    exit /b 1
)

set "BACKEND_DIR=%~dp0backend"

if not exist "%BACKEND_DIR%\venv\Scripts\activate.bat" (
    echo [INFO] Creating venv...
    python -m venv "%BACKEND_DIR%\venv"
)

echo [INFO] Installing dependencies...
call "%BACKEND_DIR%\venv\Scripts\activate.bat"
pip install -r "%BACKEND_DIR%\requirements.txt" -q

echo.
echo [INFO] Server: http://127.0.0.1:5000
echo [INFO] Press Ctrl+C to stop.
echo.

start "" http://127.0.0.1:5000

python "%BACKEND_DIR%\app.py"

pause
