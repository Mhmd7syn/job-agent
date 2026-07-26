@echo off
setlocal EnableDelayedExpansion
echo =========================================
echo       Job Agent Setup
echo =========================================

echo Checking Python installation...
python --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo Python is not installed or not in PATH! Please install Python 3.9+ first.
    pause
    exit /b
)

echo =========================================
echo Checking Git installation for auto-updates...
git --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo Git not found. Installing Git automatically...
    winget install --id Git.Git -e --source winget --accept-package-agreements --accept-source-agreements
    set "GIT_CMD=C:\Program Files\Git\cmd\git.exe"
) else (
    set "GIT_CMD=git"
)

echo Configuring repository for auto-updates...
if not exist ".git" (
    echo Initializing Git repository from ZIP...
    "!GIT_CMD!" init
    "!GIT_CMD!" remote add origin https://github.com/Mhmd7syn/job-agent.git
    "!GIT_CMD!" fetch origin
    "!GIT_CMD!" reset --mixed origin/main
    "!GIT_CMD!" branch --set-upstream-to=origin/main main
)

echo Creating Virtual Environment...
python -m venv venv
call venv\Scripts\activate.bat

echo Installing requirements...
pip install -r requirements.txt

echo Installing Playwright Browsers...
playwright install chromium

echo =========================================
echo Environment Configuration (.env)
echo =========================================
python scripts\setup_env.py


echo =========================================
echo Setting up Scheduled Task
echo =========================================
echo Please specify the days to run the background job (e.g., TUE,FRI or MON,WED,FRI or *)
set /p runDays="Days [default: TUE,FRI]: "
IF "%runDays%"=="" set runDays=TUE,FRI

echo Please specify the time to run (e.g., 05:00, 14:30)
set /p runTime="Time [default: 05:00]: "
IF "%runTime%"=="" set runTime=05:00

:: Run the script silently
schtasks /create /tn "Weekly Job Agent" /tr "wscript.exe \"%~dp0scripts\run_silent.vbs\"" /sc weekly /d %runDays% /st %runTime% /ru "%USERNAME%" /rl HIGHEST /f
echo Task configured for %runDays% at %runTime%.

echo =========================================
echo Do you want a Desktop Shortcut? (Y/N)
set /p makeShortcut="[default: Y]: "
IF "%makeShortcut%"=="" set makeShortcut=Y

if /i "%makeShortcut%"=="Y" (
    echo Creating shortcut...
    powershell -Command "$wshell = New-Object -ComObject WScript.Shell; $shortcut = $wshell.CreateShortcut('%USERPROFILE%\Desktop\Job Agent.lnk'); $shortcut.TargetPath = '%~dp0Job_Agent.bat'; $shortcut.WorkingDirectory = '%~dp0'; $shortcut.IconLocation = '%~dp0logo.ico'; $shortcut.Save()"
)

echo =========================================
echo Setup Complete! Starting the Job Agent Dashboard...
start "" "%~dp0Job_Agent.bat"
