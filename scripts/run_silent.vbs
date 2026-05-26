Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "cmd /c cd /d ""d:\projects\Jobs Search\job-agent"" && ""C:\Users\HP\AppData\Local\Python\bin\python.exe"" job_agent.py", 0
Set WshShell = Nothing
