"""Aggiornamento automatico dell'exe tramite GitHub Releases.

Flusso:
  1. `controlla()` → chiama l'API pubblica di GitHub (no token) e confronta
     il tag più recente con `conf.VERSIONE`.  Restituisce un dizionario
     con i dati della release se c'è un aggiornamento, altrimenti None.
  2. `scarica_e_installa(url_asset)` → scarica il nuovo .exe in una
     cartella temporanea e prepara un piccolo script (.bat / .sh) che:
       a. aspetta che il processo corrente si chiuda,
       b. sovrascrive il vecchio .exe col nuovo,
       c. rilancia l'applicazione.
     Infine chiude il processo corrente.

Funziona SOLO nell'exe (conf.CONGELATO = True): da sorgente non serve
aggiornare, basta fare `git pull`.  In modalità sorgente `controlla()`
restituisce sempre None.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from core import conf

# ── Cache in memoria ─────────────────────────────────────────────────────
# Il controllo è lento (~1 s per la rete): lo facciamo una volta sola in
# background e salviamo il risultato.  Le pagine leggono _cache.
_TIMEOUT_SECONDI = 5                          # timeout della richiesta HTTP
_INTERVALLO_CONTROLLO = 3600                   # secondi tra un controllo e l'altro (1 ora)

class _Cache:
    """Stato dell'ultimo controllo aggiornamenti."""
    def __init__(self):
        self.release: Optional[dict] = None    # dati della release più recente, o None
        self.controllato: bool = False          # True dopo il primo controllo
        self.ultimo_controllo: float = 0       # timestamp dell'ultimo controllo
        self.errore: Optional[str] = None      # messaggio se il controllo è fallito
        self._lock = threading.Lock()

_cache = _Cache()


# ── Funzioni pubbliche ───────────────────────────────────────────────────

def controlla(forza: bool = False) -> Optional[dict]:
    """Controlla se c'è una versione più recente su GitHub.

    Restituisce un dict ``{"tag": "v2.1.0", "nome": "...", "note": "...",
    "url_asset": "https://...", "nome_file": "TASK_v2.1.0_win64.exe"}``
    se c'è un aggiornamento, altrimenti ``None``.

    In modalità sorgente (non .exe) restituisce sempre ``None``.
    """
    if not conf.CONGELATO:
        return None

    adesso = time.time()
    with _cache._lock:
        if (_cache.controllato and not forza
                and adesso - _cache.ultimo_controllo < _INTERVALLO_CONTROLLO):
            return _cache.release

    # Chiamata all'API di GitHub (senza autenticazione: 60 req/h per IP)
    url = f"https://api.github.com/repos/{conf.GITHUB_REPO}/releases/latest"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "TASK-updater"}
    req = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDI) as risposta:
            dati = json.loads(risposta.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, json.JSONDecodeError) as e:
        with _cache._lock:
            _cache.errore = str(e)
            _cache.controllato = True
            _cache.ultimo_controllo = adesso
        print(f"[aggiorna] Controllo fallito: {e}", flush=True)
        return None

    tag = dati.get("tag_name", "")
    versione_remota = tag.lstrip("vV")
    # Confronto semantico semplice: "2.1.0" > "2.0.0"
    if not _versione_piu_recente(versione_remota, conf.VERSIONE):
        with _cache._lock:
            _cache.release = None
            _cache.controllato = True
            _cache.ultimo_controllo = adesso
            _cache.errore = None
        return None

    # Cerco l'asset .exe (o .zip) tra gli allegati della release
    asset = _trova_asset(dati.get("assets", []))
    risultato = {
        "tag": tag,
        "versione": versione_remota,
        "nome": dati.get("name", tag),
        "note": dati.get("body", ""),
        "url_asset": asset["browser_download_url"] if asset else None,
        "nome_file": asset["name"] if asset else None,
        "dimensione": asset.get("size", 0) if asset else 0,
    }

    with _cache._lock:
        _cache.release = risultato
        _cache.controllato = True
        _cache.ultimo_controllo = adesso
        _cache.errore = None

    print(f"[aggiorna] Nuova versione disponibile: {tag}", flush=True)
    return risultato


def controlla_in_background() -> None:
    """Lancia il controllo in un thread separato (non blocca l'avvio)."""
    threading.Thread(target=controlla, daemon=True, name="aggiorna-check").start()


def release_disponibile() -> Optional[dict]:
    """Lettura veloce della cache (per il context_processor, niente rete)."""
    with _cache._lock:
        return _cache.release


def scarica_e_installa(url_asset: str) -> str:
    """Scarica il nuovo exe e prepara lo script di sostituzione.

    Restituisce un messaggio di stato.  L'applicazione si chiude da sola
    dopo aver lanciato lo script.
    """
    if not conf.CONGELATO or not url_asset:
        return "Aggiornamento disponibile solo nell'exe."

    exe_corrente = Path(sys.executable).resolve()
    cartella_temp = Path(tempfile.mkdtemp(prefix="task_update_"))
    nuovo_exe = cartella_temp / exe_corrente.name

    # 1. Scarico il file
    print(f"[aggiorna] Scarico {url_asset} …", flush=True)
    try:
        urllib.request.urlretrieve(url_asset, str(nuovo_exe))
    except Exception as e:
        shutil.rmtree(cartella_temp, ignore_errors=True)
        raise RuntimeError(f"Download fallito: {e}") from e
    print(f"[aggiorna] Download completato: {nuovo_exe}", flush=True)

    # 2. Preparo lo script che sostituisce l'exe dopo la chiusura
    if sys.platform == "win32":
        _script_windows(exe_corrente, nuovo_exe, cartella_temp)
    else:
        _script_unix(exe_corrente, nuovo_exe, cartella_temp)

    # 3. Chiudo il processo corrente (il watchdog/Flask si spegne)
    print("[aggiorna] Chiudo per applicare l'aggiornamento…", flush=True)
    threading.Timer(1.0, lambda: os._exit(0)).start()
    return "Aggiornamento in corso: TASK si riavvierà automaticamente."


# ── Utilità interne ──────────────────────────────────────────────────────

def _versione_piu_recente(remota: str, locale: str) -> bool:
    """True se `remota` è strettamente più recente di `locale` (confronto semantico)."""
    try:
        parti_r = [int(x) for x in remota.split(".")]
        parti_l = [int(x) for x in locale.split(".")]
        return parti_r > parti_l
    except (ValueError, AttributeError):
        return False


def _trova_asset(assets: list) -> Optional[dict]:
    """Cerca il primo asset .exe (Windows) oppure .zip/.dmg tra gli allegati."""
    preferiti = (".exe",)
    tutti = (".exe", ".zip", ".dmg", ".tar.gz")
    for ext in preferiti:
        for a in assets:
            if a.get("name", "").lower().endswith(ext):
                return a
    for ext in tutti:
        for a in assets:
            if a.get("name", "").lower().endswith(ext):
                return a
    return assets[0] if assets else None


def _script_windows(exe_vecchio: Path, exe_nuovo: Path, cartella_temp: Path) -> None:
    """Crea e lancia un .bat che aspetta, sostituisce e rilancia."""
    bat = cartella_temp / "_aggiorna.bat"
    bat.write_text(textwrap.dedent(f"""\
        @echo off
        echo Aggiornamento TASK in corso...
        timeout /t 3 /nobreak >nul
        :riprova
        copy /y "{exe_nuovo}" "{exe_vecchio}" >nul 2>&1
        if errorlevel 1 (
            timeout /t 2 /nobreak >nul
            goto riprova
        )
        start "" "{exe_vecchio}"
        rmdir /s /q "{cartella_temp}"
    """), encoding="utf-8")
    subprocess.Popen(
        ["cmd", "/c", str(bat)],
        creationflags=subprocess.CREATE_NO_WINDOW,
        close_fds=True,
    )


def _script_unix(exe_vecchio: Path, exe_nuovo: Path, cartella_temp: Path) -> None:
    """Crea e lancia uno script shell che aspetta, sostituisce e rilancia."""
    sh = cartella_temp / "_aggiorna.sh"
    sh.write_text(textwrap.dedent(f"""\
        #!/bin/bash
        sleep 3
        cp -f "{exe_nuovo}" "{exe_vecchio}"
        chmod +x "{exe_vecchio}"
        open "{exe_vecchio}" 2>/dev/null || "{exe_vecchio}" &
        rm -rf "{cartella_temp}"
    """))
    sh.chmod(0o755)
    subprocess.Popen(["/bin/bash", str(sh)], close_fds=True)
