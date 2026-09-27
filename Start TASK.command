#!/bin/bash
# Avvio con doppio clic su Mac: per chiudere il programma basta chiudere la finestra del Terminale.
# La prima volta macOS può bloccarlo: tasto destro sul file -> Apri -> Apri.
cd "$(dirname "$0")" || exit 1

# Cerco un Python 3.10 o più recente (il python3 di sistema del Mac può essere più vecchio).
PY=""
for candidato in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$candidato" >/dev/null 2>&1 && \
     "$candidato" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
    PY="$candidato"
    break
  fi
done

if [ -z "$PY" ]; then
  osascript -e 'display dialog "Per usare TASK serve Python 3.10 o più recente.\n\nTi apro la pagina di download: installa Python, poi riapri questo file." with title "FITP Manager" buttons {"OK"} with icon caution' >/dev/null 2>&1
  open "https://www.python.org/downloads/"
  exit 1
fi

"$PY" avvia.py
