' Comm. Claude: sostituisce "Start TASK.bat". Doppio clic su "Start TASK.vbs" -> avvia.py, SENZA finestra nera.
' Usa pyw/pythonw (Python senza console) e nasconde anche i comandi di controllo (Run ..., 0).
' Solo caratteri ASCII: Windows legge i .vbs nella codifica locale, le lettere accentate uscirebbero storte.
Option Explicit
Dim shell, fso, cartella, python

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
cartella = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = cartella

' pyw = launcher di python.org (sceglie il Python 3 piu' recente); pythonw = Python nel PATH.
' Il controllo della versione (>= 3.10) lo fa avvia.py, con un riquadro d'errore.
python = ""
If shell.Run("cmd /c where pyw", 0, True) = 0 Then
    python = "pyw -3"
ElseIf shell.Run("cmd /c where pythonw", 0, True) = 0 Then
    python = "pythonw"
End If

If python = "" Then
    MsgBox "Per usare TASK serve Python 3.10 o piu' recente." & vbCrLf & vbCrLf & _
           "Ti apro la pagina di download: durante l'installazione spunta ""Add python.exe to PATH""," & vbCrLf & _
           "poi riapri questo file.", vbExclamation, "TASK"
    shell.Run "https://www.python.org/downloads/"
    WScript.Quit 1
End If

' 0 = finestra nascosta, False = non aspetto: lo script finisce subito, avvia.py continua da solo.
shell.Run python & " """ & cartella & "\avvia.py""", 0, False
