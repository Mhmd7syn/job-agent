@echo off
setlocal
cd /d "%~dp0"

if not exist ".git" goto LaunchApp
git --version >nul 2>&1
if not %errorlevel%==0 goto LaunchApp

echo Checking for updates from GitHub...
git fetch >nul 2>&1
git status -uno | findstr /c:"Your branch is behind" >nul
if not %errorlevel%==0 goto LaunchApp

echo.
echo ==========================================
echo An update is available for Job Agent!
echo ==========================================
set /p updateChoice="Do you want to download and apply the update? (Y/N) [Y]: "
if /I "%updateChoice%"=="N" goto LaunchApp

echo Downloading update...
git fetch origin main >nul 2>&1
git reset --hard origin/main

:LaunchApp
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
    start "" "venv\Scripts\pythonw.exe" desktop_app.pyw
) else (
    echo Virtual environment not found. Running setup...
    call setup.bat
)
