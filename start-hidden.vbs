' Runs host.ps1 with no window at all, so nothing flashes on screen or over a game.
' The start-up task from install-startup.ps1 runs this file.
Set shell = CreateObject("WScript.Shell")
folder = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
command = "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & folder & "\host.ps1"""
WScript.Quit shell.Run(command, 0, True)
