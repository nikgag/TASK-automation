; Comm. Claude: ricetta dell'installer (Inno Setup 6). La usa strumenti\crea_installer_windows.bat dopo PyInstaller.
; Installa per il solo utente corrente (nessun permesso di amministratore) in AppData\Local\Programs\TASK,
; crea le icone nel menu Start e sul desktop e avvia TASK alla fine. I dati dell'utente stanno in
; AppData\Local\TASK e NON vengono toccati da aggiornamenti o disinstallazione.

; versione: da aumentare a ogni nuova versione distribuita
#define Versione "2.0.3"

[Setup]
; AppId: identifica TASK per aggiornamenti e disinstallazione. Non cambiarlo mai.
AppId={{E5DB1A9F-5B4A-4E37-8AC3-2CD84DED250A}
AppName=TASK
AppVersion={#Versione}
AppVerName=TASK {#Versione}
AppPublisher=T.A.S.K. - Tennis Automation System Kit
DefaultDirName={autopf}\TASK
DefaultGroupName=TASK
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=TASK-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\TASK.exe
; se TASK è aperto durante un aggiornamento, l'installer lo chiude
CloseApplications=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "it"; MessagesFile: "compiler:Languages\Italian.isl"

[Files]
Source: "..\dist\TASK\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; a ogni aggiornamento tolgo la vecchia cartella _internal: niente librerie vecchie rimaste in giro
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\TASK"; Filename: "{app}\TASK.exe"
Name: "{autodesktop}\TASK"; Filename: "{app}\TASK.exe"

[Run]
; Comm. Claude: tolto skipifsilent: dopo l'aggiornamento silenzioso lanciato da core/aggiorna.py TASK deve ripartire da solo
Filename: "{app}\TASK.exe"; Description: "Avvia TASK"; Flags: nowait postinstall
