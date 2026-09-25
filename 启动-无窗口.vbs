' 无控制台窗口启动 ok-dna-mod
Set fso = CreateObject("Scripting.FileSystemObject")
Set ws = CreateObject("WScript.Shell")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
ws.CurrentDirectory = dir
ws.Run "pythonw """ & dir & "\main.py""", 0, False
