@echo off
rem Comm. Claude: crea dist\TASK-Setup.exe (installer di TASK per Windows). Doppio clic su questo file,
rem oppure da terminale nella cartella del progetto:  strumenti\crea_installer_windows.bat
rem Serve: Python 3.10+ (solo su QUESTO pc, non su quelli degli utenti), Inno Setup 6, data\circolo_regioni.csv.
setlocal
chcp 65001 >nul
cd /d "%~dp0\.."

if not exist "data\circolo_regioni.csv" (
  echo ERRORE: manca data\circolo_regioni.csv. Copialo in data\ e rilancia.
  goto :fine_errore
)

rem Inno Setup: installazione per tutti o solo per l'utente (winget lo mette in AppData\Local\Programs)
set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC (
  echo ERRORE: Inno Setup 6 non trovato. Installalo con:  winget install JRSoftware.InnoSetup
  echo oppure da https://jrsoftware.org/isdl.php  e rilancia.
  goto :fine_errore
)

rem Ambiente di build separato (.venv-build): non tocca l'eventuale .venv di sviluppo
if not exist ".venv-build\Scripts\python.exe" (
  echo Creo l'ambiente di build...
  py -3 -m venv .venv-build || goto :fine_errore
)
echo Installo le librerie e PyInstaller...
".venv-build\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt pyinstaller || goto :fine_errore

echo Creo l'exe con PyInstaller (qualche minuto)...
".venv-build\Scripts\python.exe" -m PyInstaller --noconfirm --clean --distpath dist --workpath build strumenti\task.spec || goto :fine_errore

echo Creo l'installer con Inno Setup...
"%ISCC%" /Q strumenti\task_installer.iss || goto :fine_errore

echo.
echo FATTO: dist\TASK-Setup.exe  ^<-- questo e' il file da dare agli utenti
pause
exit /b 0

:fine_errore
echo.
echo Creazione dell'installer NON riuscita: leggi il messaggio qui sopra.
pause
exit /b 1
