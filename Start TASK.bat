@echo off
rem Avvio con doppio clic su Windows: per chiudere il programma basta chiudere la finestra.
chcp 65001 >nul
title FITP Manager
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo.
  echo Per usare FITP Manager serve Python 3.10 o piu' recente.
  echo Ti apro la pagina di download: durante l'installazione spunta "Add python.exe to PATH",
  echo poi riapri questo file.
  start "" https://www.python.org/downloads/
  pause
  exit /b 1
)

%PY% avvia.py
if errorlevel 1 pause
