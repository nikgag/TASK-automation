"""Aggiornamento automatico dell'exe tramite GitHub Releases.

Flusso:
  1. `controlla()` → chiama l'API pubblica di GitHub (no token) e confronta
     il tag più recente con `conf.VERSIONE`.  Restituisce un dizionario
     con i dati della release se c'è un aggiornamento, altrimenti None.
  2. `scarica_e_installa(url_asset)` → scarica TASK-Setup.exe (l'installer
     allegato alla Release) in una cartella temporanea, controlla che il file
     sia intero e lo lancia in modalità silenziosa. Poi TASK si chiude da solo:
     l'installer sostituisce i file del programma e al termine riavvia TASK.

#Comm. Claude:  docstring riscritta. Prima il file scaricato (l'installer!) veniva copiato sopra TASK.exe da un .bat
#Comm. Claude:  in loop senza limite e senza finestra: ora si esegue l'installer, che sa già aggiornare i file (stesso AppId).

Funziona SOLO nell'exe per Windows (conf.CONGELATO = True): da sorgente non serve
aggiornare, basta fare `git pull`.  In modalità sorgente `controlla()`
restituisce sempre None.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
#Comm. Claude:  tolto "import textwrap": serviva solo a scrivere i vecchi script .bat/.sh
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

#Comm. Claude:  costanti nuove per il download: un limite a ogni attesa, così una rete lenta o un file difettoso
#Comm. Claude:  producono un errore chiaro (mostrato nella pagina) invece di un'attesa infinita
_TIMEOUT_DOWNLOAD = 30                         # s senza ricevere dati: oltre, il download fallisce
_DURATA_MAX_DOWNLOAD = 600                     # s: tetto totale del download (10 minuti)
_DIMENSIONE_MIN = 10 * 1024 * 1024             # byte: l'installer pesa ~50 MB; sotto i 10 MB è un file sbagliato
#Comm. Claude:  flag di Windows (valori fissi, definiti qui per non dipendere dal sistema): l'installer parte come
#Comm. Claude:  processo indipendente e NON si chiude quando TASK termina
_DETACHED_PROCESS = 0x00000008
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_in_aggiornamento = threading.Lock()           # evita due download insieme se si clicca due volte "Aggiorna ora"

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
    "url_asset": "https://...", "nome_file": "TASK-Setup.exe"}``
    se c'è un aggiornamento, altrimenti ``None``.

    In modalità sorgente (non .exe) restituisce sempre ``None``.
    """
    #Comm. Claude:  aggiunto sys.platform: la Release contiene solo l'installer Windows, quindi su altri sistemi
    #Comm. Claude:  il banner mostrerebbe un pulsante "Aggiorna ora" che non può funzionare
    if not conf.CONGELATO or sys.platform != "win32":
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
    _pulisci_vecchi_download()   #Comm. Claude:  toglie i residui dell'aggiornamento precedente (cartelle task_update_* in TEMP)
    threading.Thread(target=controlla, daemon=True, name="aggiorna-check").start()


def release_disponibile() -> Optional[dict]:
    """Lettura veloce della cache (per il context_processor, niente rete)."""
    with _cache._lock:
        return _cache.release


def scarica_e_installa(url_asset: str) -> str:
    """Scarica TASK-Setup.exe e lo lancia in silenzioso; TASK si chiude e l'installer lo aggiorna e lo riavvia.

    Restituisce un messaggio di stato. Se qualcosa va storto solleva RuntimeError con un testo chiaro
    (la rotta /aggiorna di app.py lo mostra nella pagina).
    """
    #Comm. Claude:  funzione riscritta (vedi docstring del modulo): scarica l'installer con timeout e controlli,
    #Comm. Claude:  lo esegue in silenzioso e chiude TASK. Nessun .bat, nessun loop: se qualcosa va storto c'è un errore.
    if not conf.CONGELATO or sys.platform != "win32" or not url_asset:
        return "Aggiornamento automatico disponibile solo nell'exe per Windows."
    # l'indirizzo arriva dall'API di GitHub, ma lo riconfermo: deve essere un allegato di QUESTO repository
    prefisso = f"https://github.com/{conf.GITHUB_REPO}/releases/download/".lower()
    if not url_asset.lower().startswith(prefisso):
        raise RuntimeError(f"indirizzo di download non riconosciuto: {url_asset}")
    if not _in_aggiornamento.acquire(blocking=False):
        return "Aggiornamento già in corso: attendi qualche istante."

    cartella_temp = Path(tempfile.mkdtemp(prefix="task_update_"))
    try:
        setup = cartella_temp / "TASK-Setup.exe"
        print(f"[aggiorna] Scarico {url_asset} …", flush=True)
        _scarica(url_asset, setup, _dimensione_attesa(url_asset))
        print(f"[aggiorna] Download completato: {setup}", flush=True)
        _lancia_installer(setup)
    except Exception:
        shutil.rmtree(cartella_temp, ignore_errors=True)
        _in_aggiornamento.release()
        raise   # l'errore arriva intero alla rotta /aggiorna (nessun errore nascosto)

    # L'installer è partito. Se TASK restasse aperto gli bloccherebbe i file da sostituire: mi chiudo io
    # dopo 1 s (il tempo di rispondere al browser). Il lock resta preso: il processo sta per terminare.
    print("[aggiorna] Installer avviato: chiudo TASK per applicare l'aggiornamento…", flush=True)
    threading.Timer(1.0, _chiudi_programma).start()
    return "Aggiornamento in corso: TASK si riavvierà da solo tra poco."


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


#Comm. Claude:  funzioni nuove (sostituiscono _script_windows/_script_unix, rimossi)
def _dimensione_attesa(url_asset: str) -> int:
    """Dimensione in byte dell'allegato, come dichiarata da GitHub (0 se non la conosco)."""
    rel = release_disponibile()
    return rel.get("dimensione", 0) if rel and rel.get("url_asset") == url_asset else 0


def _scarica(url: str, destinazione: Path, attesa: int) -> None:
    """Scarica `url` in `destinazione` a blocchi. Errore chiaro se lento, incompleto o non è un programma Windows."""
    richiesta = urllib.request.Request(url, headers={"User-Agent": "TASK-updater"})
    inizio = time.time()
    ricevuti = 0
    try:
        with urllib.request.urlopen(richiesta, timeout=_TIMEOUT_DOWNLOAD) as risposta, \
                open(destinazione, "wb") as file:
            while True:
                blocco = risposta.read(1024 * 1024)
                if not blocco:
                    break
                file.write(blocco)
                ricevuti += len(blocco)
                if time.time() - inizio > _DURATA_MAX_DOWNLOAD:
                    raise RuntimeError("il download dura troppo (oltre 10 minuti): controlla la connessione e riprova")
    except OSError as e:   # comprende URLError, HTTPError e il timeout di rete
        raise RuntimeError(f"download fallito: {e}") from e

    if attesa and ricevuti != attesa:
        raise RuntimeError(f"file scaricato incompleto ({ricevuti} byte invece di {attesa}): riprova")
    if ricevuti < _DIMENSIONE_MIN:
        raise RuntimeError(f"file scaricato troppo piccolo ({ricevuti} byte): non sembra l'installer")
    with open(destinazione, "rb") as file:
        if file.read(2) != b"MZ":   # ogni .exe di Windows comincia con queste due lettere
            raise RuntimeError("il file scaricato non è un programma Windows valido")


def _lancia_installer(setup: Path) -> None:
    """Avvia l'installer in silenzioso, come processo indipendente. Scrive il dettaglio in aggiornamento.log."""
    log = conf.DATI_DIR / "aggiornamento.log"   # utile se un aggiornamento non riesce: è il registro di Inno Setup
    # /VERYSILENT nessuna finestra | /SUPPRESSMSGBOXES nessun riquadro | /NORESTART mai riavviare il PC
    # /CLOSEAPPLICATIONS chiude i programmi che bloccano i file | /LOG scrive il registro dell'installazione
    # Stringa unica (non lista): Inno Setup vuole le virgolette attorno al percorso del log, anche con spazi.
    comando = f'"{setup}" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS /LOG="{log}"'
    subprocess.Popen(comando, creationflags=_DETACHED_PROCESS | _CREATE_NEW_PROCESS_GROUP, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _chiudi_programma() -> None:
    """Termina TASK subito, da tutti i thread (come fa il watchdog di app.py)."""
    os._exit(0)


def _pulisci_vecchi_download() -> None:
    """Cancella da TEMP le cartelle task_update_* vecchie di oltre 10 minuti (residui di un aggiornamento passato)."""
    if not conf.CONGELATO:
        return
    limite = time.time() - 600
    for cartella in Path(tempfile.gettempdir()).glob("task_update_*"):
        if cartella.is_dir() and cartella.stat().st_mtime < limite:
            shutil.rmtree(cartella, ignore_errors=True)   # file ancora in uso: lo si riprova al prossimo avvio