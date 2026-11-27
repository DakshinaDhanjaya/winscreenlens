Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
strDir = fso.GetParentFolderName(WScript.ScriptFullName)
strPythonw = strDir & "\.venv\Scripts\pythonw.exe"
strRun = strDir & "\run.py"

If Not fso.FileExists(strPythonw) Then
    strPythonw = "C:\Python314\pythonw.exe"
End If

WshShell.CurrentDirectory = strDir
WshShell.Run Chr(34) & strPythonw & Chr(34) & " " & Chr(34) & strRun & Chr(34), 0, False
Set WshShell = Nothing
Set fso = Nothing
