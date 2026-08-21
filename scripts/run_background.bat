@echo off
setlocal
cd /d "%~dp0\.."

:: Ensure output directory exists for logs
if not exist "output" mkdir output

if exist ".git" (
    git --version >nul 2>&1
    if %errorlevel%==0 (
        set "IS_DIRTY="
        for /f "tokens=*" %%i in ('git status --porcelain 2^>nul') do set "IS_DIRTY=1"
        if not "%IS_DIRTY%"=="" (
            echo [%DATE% %TIME%] Local modifications detected. Skipping background git update. >> output\cron.log
        ) else (
            echo [%DATE% %TIME%] Checking for updates from GitHub... >> output\cron.log
            if exist "core\config.py" copy /y "core\config.py" "core\config.py.bak" >nul 2>&1
            if exist "core\config.json" copy /y "core\config.json" "core\config.json.bak" >nul 2>&1
            git fetch origin main >nul 2>&1
            git pull origin main --autostash >> output\cron.log 2>&1
            if exist "core\config.py.bak" copy /y "core\config.py.bak" "core\config.py" >nul 2>&1
            if exist "core\config.json.bak" copy /y "core\config.json.bak" "core\config.json" >nul 2>&1
            if exist "core\config.py.bak" del /f /q "core\config.py.bak" >nul 2>&1
            if exist "core\config.json.bak" del /f /q "core\config.json.bak" >nul 2>&1
        )
    )
)

if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
    echo [%DATE% %TIME%] Starting background scraper... >> output\cron.log
    python job_agent.py >> output\cron.log 2>&1
) else (
    echo [%DATE% %TIME%] VENV not found. >> output\cron.log
)
