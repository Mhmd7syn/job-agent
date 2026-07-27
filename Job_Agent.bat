@echo off
setlocal
cd /d "%~dp0"

:: If virtual environment does not exist yet (first-time setup), skip update checking!
if not exist "venv\Scripts\activate.bat" goto RunSetup

if not exist ".git" goto LaunchApp
git --version >nul 2>&1
if not %errorlevel%==0 goto LaunchApp

echo Checking for updates from GitHub...
git fetch --depth=1 origin main >nul 2>&1
for /f "tokens=*" %%i in ('git rev-parse HEAD 2^>nul') do set "LOCAL_REV=%%i"
for /f "tokens=*" %%i in ('git rev-parse origin/main 2^>nul') do set "REMOTE_REV=%%i"
if "%LOCAL_REV%"=="" goto LaunchApp
if "%REMOTE_REV%"=="" goto LaunchApp
if "%LOCAL_REV%"=="%REMOTE_REV%" goto LaunchApp

echo.
echo ==========================================
echo An update is available for Job Agent!
echo ==========================================
set /p updateChoice="Do you want to download and apply the update? (Y/N) [Y]: "
if /I "%updateChoice%"=="N" goto LaunchApp

:: Wrap git update in parenthesized block to prevent CMD from reading corrupted file offsets when script is updated on disk
(
    echo Downloading and applying update...
    git fetch --depth=1 origin main >nul 2>&1
    git reset --hard origin/main >nul 2>&1
    echo Update applied successfully! Re-launching updated Job Agent...
    timeout /t 1 /nobreak >nul
    start "" "%~f0"
    exit /b 0
)

:LaunchApp
call venv\Scripts\activate.bat
start "" "venv\Scripts\pythonw.exe" desktop_app.pyw
exit /b 0

:RunSetup
echo Virtual environment not found. Starting setup wizard...
call Setup_Job_Agent.bat
exit /b 0
