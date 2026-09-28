#!/bin/bash
# Comm. Claude: lanciatore Mac. Gira DENTRO "Start TASK.app" (Contents/Resources/avvio_mac.sh), chiamato dall'applet.
# Questo è il sorgente: dopo una modifica ricrea l'app con  bash strumenti/crea_app_mac.sh
# Perché un'applet e non un semplice script nell'app: macOS protegge Scrivania/Documenti/Download (TCC).
# Uno script non firmato riceve un "Operation not permitted" SENZA che compaia la richiesta di permesso;
# un'applet firmata invece fa comparire "Start TASK vorrebbe accedere alla cartella Scrivania" -> Consenti.

LOG="${TMPDIR:-/tmp}/TASK-avvio.log"           # errori prima che avvia.py apra avvio.log
SEGNALE="${TMPDIR:-/tmp}/TASK-partito"          # avvia.py lo crea quando è partito davvero
: > "$LOG"; rm -f "$SEGNALE"
errore() {   # riquadro di errore con le ultime righe del registro
  local testo
  testo="$1\n\n$(tail -n 8 "$LOG" | sed 's/\\/\\\\/g; s/"/\\"/g' | awk '{printf "%s\\n", $0}')"
  osascript -e "display dialog \"$testo\" with title \"TASK\" buttons {\"OK\"} default button 1 with icon stop" >/dev/null 2>&1
  exit 1
}

# Lo script è in <progetto>/Start TASK.app/Contents/Resources/: risalgo di tre cartelle.
cd "$(dirname "$0")/../../.." 2>>"$LOG" || errore "Non riesco ad aprire la cartella del programma."

# Aperta dal Finder l'app ha un PATH minimo: prendo quello della shell dell'utente (come il Terminale)
# più le cartelle standard di python.org e Homebrew.
PATH_UTENTE="$("${SHELL:-/bin/zsh}" -ilc 'printf %s "$PATH"' </dev/null 2>/dev/null)"
export PATH="$PATH_UTENTE:/Library/Frameworks/Python.framework/Versions/Current/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"

# Python 3.10 o più recente. /usr/bin/python3 senza Command Line Tools è un segnaposto che chiede
# di installarli: lo salto.
PY=""
for candidato in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
  percorso="$(command -v "$candidato" 2>/dev/null)" || continue
  if [ "$percorso" = "/usr/bin/python3" ] && ! xcode-select -p >/dev/null 2>&1; then continue; fi
  if "$percorso" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
    PY="$percorso"
    break
  fi
done
if [ -z "$PY" ]; then
  osascript -e 'display dialog "Per usare TASK serve Python 3.10 o più recente.\n\nTi apro la pagina di download: installa Python, poi riapri TASK." with title "TASK" buttons {"OK"} default button 1 with icon caution' >/dev/null 2>&1
  open "https://www.python.org/downloads/"
  exit 1
fi
echo "Python: $PY" >> "$LOG"

# avvia.py staccato (l'app deve chiudersi: un secondo doppio clic deve poter lanciare una nuova istanza,
# così avvia.py riapre il browser se TASK è già aperto).
TASK_SEGNALE="$SEGNALE" nohup "$PY" avvia.py </dev/null >>"$LOG" 2>&1 &
PID=$!

# Aspetto che avvia.py confermi di essere partito (ha letto la cartella e aperto avvio.log).
# Fino a 120 s: il tempo di rispondere alla richiesta di permesso di macOS. L'icona resta nel Dock intanto.
for _ in $(seq 120); do
  [ -e "$SEGNALE" ] && exit 0
  if ! kill -0 "$PID" 2>/dev/null; then
    wait "$PID"; codice=$?
    [ "$codice" -eq 0 ] && exit 0
    if grep -q "Operation not permitted" "$LOG"; then
      errore "macOS non lascia a TASK leggere la sua cartella.\n\nImpostazioni di Sistema -> Privacy e sicurezza -> File e cartelle: attiva \"Start TASK\", poi riapri."
    fi
    errore "TASK non è partito (codice $codice)."
  fi
  sleep 1
done
exit 0
