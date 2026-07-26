@echo off
setlocal
cd /d "%~dp0\.."

:: Ensure output directory exists for logs
if not exist "output" mkdir output

if exist ".git" (
    git --version >nul 2>&1
    if %errorlevel%==0 (
        echo [%DATE% %TIME%] Checking for updates from GitHub... >> output\cron.log
        git fetch origin main >> output\cron.log 2>&1
        git reset --hard origin/main >> output\cron.log 2>&1
    )
)

if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
    echo [%DATE% %TIME%] Starting background scraper... >> output\cron.log
    python job_agent.py >> output\cron.log 2>&1
) else (
    echo [%DATE% %TIME%] VENV not found. >> output\cron.log
)
