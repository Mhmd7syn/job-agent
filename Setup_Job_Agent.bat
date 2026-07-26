@echo off
setlocal
cd /d "%~dp0"

:: Check if setup_ui.pyw is present. If not, download it automatically from GitHub!
if not exist "setup_ui.pyw" (
    echo Downloading Job Agent graphical installer...
    powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/Mhmd7syn/job-agent/main/setup_ui.pyw' -OutFile 'setup_ui.pyw' -UseBasicParsing" >nul 2>&1
)

:: Try launching via pythonw (zero console window)
pythonw --version >nul 2>&1
if %errorlevel% equ 0 (
    start "" pythonw.exe setup_ui.pyw
    exit /b
)

:: Try launching via regular python
python --version >nul 2>&1
if %errorlevel% equ 0 (
    start "" python.exe setup_ui.pyw
    exit /b
)

:: If Python is missing, attempt automated installation via winget or alert user
echo Python 3.9+ was not found! Installing Python automatically via Winget...
winget install --id Python.Python.3.11 -e --source winget --accept-package-agreements --accept-source-agreements
if %errorlevel% equ 0 (
    start "" pythonw.exe setup_ui.pyw
    exit /b
) else (
    powershell -Command "[System.Windows.Forms.MessageBox]::Show('Python 3.9+ is not installed or not in system PATH! Please install Python from python.org to run Job Agent setup.', 'Job Agent Setup Error', 'OK', 'Error')"
    exit /b
)
