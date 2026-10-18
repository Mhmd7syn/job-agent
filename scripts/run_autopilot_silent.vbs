Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")
strPath = FSO.GetParentFolderName(WScript.ScriptFullName)
strBat = """" & strPath & "\run_autopilot.bat"""
WshShell.Run strBat, 0
Set WshShell = Nothing
