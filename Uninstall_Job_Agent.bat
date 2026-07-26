@echo off
setlocal
cd /d "%~dp0"

pythonw --version >nul 2>&1
if %errorlevel% equ 0 (
    start "" pythonw.exe uninstall_ui.pyw
    exit /b
)

python --version >nul 2>&1
if %errorlevel% equ 0 (
    start "" python.exe uninstall_ui.pyw
    exit /b
)

echo Python is required to run the uninstaller UI.
pause
