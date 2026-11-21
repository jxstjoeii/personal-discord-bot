' Runs sync.ps1 with no window at all, so the hourly GitHub sync never flashes a
' command prompt over a game. install-startup.ps1 points the hourly sync task here.
Set shell = CreateObject("WScript.Shell")
folder = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
command = "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & folder & "\sync.ps1"""
WScript.Quit shell.Run(command, 0, True)
