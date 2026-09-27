#!/bin/bash
# Comm. Claude: ricrea "Start TASK.app" (solo su Mac, per lo sviluppatore). Da rilanciare dopo aver
# modificato strumenti/avvio_mac.sh, poi fai commit dell'app.
# L'app è un'applet AppleScript (osacompile) firmata ad-hoc: così macOS mostra la richiesta di accesso
# alla Scrivania/Documenti invece di negarla in silenzio come fa con uno script non firmato.
set -euo pipefail
cd "$(dirname "$0")/.."
APP="Start TASK.app"

rm -rf "$APP"
osacompile -o "$APP" \
  -e 'try' \
  -e '  do shell script quoted form of (POSIX path of (path to me) & "Contents/Resources/avvio_mac.sh")' \
  -e 'end try'   # gli errori li mostra già avvio_mac.sh: niente secondo riquadro di AppleScript
cp strumenti/avvio_mac.sh "$APP/Contents/Resources/avvio_mac.sh"
chmod +x "$APP/Contents/Resources/avvio_mac.sh"
plutil -replace CFBundleIdentifier -string "local.task.webapp" "$APP/Contents/Info.plist"
plutil -replace CFBundleName -string "TASK" "$APP/Contents/Info.plist"
codesign --force --sign - "$APP"          # firma ad-hoc: dopo QUALSIASI modifica all'app va rifatta
codesign --verify --strict "$APP"
echo "Creata e firmata: $APP"
