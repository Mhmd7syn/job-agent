@echo off
setlocal
cd /d "%~dp0\.."

if not exist "output" mkdir output

if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
    echo [%DATE% %TIME%] Starting Auto-Pilot background cycle... >> output\autopilot_cron.log
    python -m appliers.master_orchestrator >> output\autopilot_cron.log 2>&1
) else (
    echo [%DATE% %TIME%] VENV not found. >> output\autopilot_cron.log
)
