# Client del DB circoli condiviso: l'unico punto di TASK che parla con il
# portinaio (strumenti/apps_script/circoli.gs). Gli altri script usano solo queste funzioni.
"""DB circoli condiviso: Google Sheet privato, raggiungibile solo tramite il portinaio (Apps Script).

  collegato()              True se su questo computer c'è il codice di accesso
  collega(token)           lo prova sul portinaio e, solo se funziona, lo salva (riquadro "Collega il DB")
  salva_config(token)      lo salva FUORI dalla cartella del progetto (senza provarlo)
  L'indirizzo del portinaio è fisso: conf.URL_DB_CIRCOLI.
  cerca(nomi)              {NOME MAIUSCOLO: (provincia, regione)} solo per i circoli trovati
  province()               {provincia: regione} per la tendina dell'Excel
  aggiungi(righe)          [(circolo, provincia), ...] -> il portinaio ricontrolla e scrive in fondo
  stato()                  {"totale": n, "ultima_aggiunta": "aaaa-mm-gg hh:mm:ss"}
  registra_uso(funzione)   +1 nel contatore dell'utente (foglio Utenti), in sottofondo, senza aspettare

Errori (tutti ErroreUtente, messaggio "Err NN: ..." come nel resto dell'app):
  Err 60 rete assente / portinaio non raggiungibile   Err 61-64 rifiutato dal portinaio
  Err 67 la richiesta arriva a Google ma la risposta no (dopo TENTATIVI tentativi)
  Err 65 DB non collegato su questo computer
Niente copia locale: senza rete TASK non lavora comunque (driver FITP), quindi si ferma subito.
"""
from __future__ import annotations

import json
import os
import socket
import ssl
import threading
import urllib.error
import urllib.request

from core import conf
from core.errori import ErroreUtente

# attese brevi e più tentativi. Lo script su Google risponde in 1-4 s, ma ogni tanto (circa una
# chiamata su 5-6 nei test, via IPv4 e IPv6, su reti diverse) la risposta non arriva mai: aspettare
# 30 s era inutile, riprovare invece funziona quasi sempre. Vale per TUTTE le azioni: "uso" in quel
# caso raro può contare due volte, "aggiungi" è protetto dal portinaio (scarta i doppioni).
TIMEOUT_S = 12
TENTATIVI = 3
MAX_NOMI = 2000                 # come nel portinaio: oltre, la ricerca si fa a blocchi


# ---------------------------------------------------------------------------
# Configurazione locale (solo il token): conf.CONFIG_DB_CIRCOLI, mai nella cartella del progetto
# ---------------------------------------------------------------------------
def collegato() -> bool:
    return conf.CONFIG_DB_CIRCOLI.is_file()


def _config() -> dict:
    if not collegato():
        raise ErroreUtente("Err 65: DB circoli non collegato su questo computer: "
                           "incolla il codice di accesso nella scheda «Circoli».")
    token = json.loads(conf.CONFIG_DB_CIRCOLI.read_text(encoding="utf-8")).get("token", "")
    if not token:
        raise ErroreUtente(f"Err 65: codice di accesso al DB circoli mancante in {conf.CONFIG_DB_CIRCOLI}.")
    return {"url": conf.URL_DB_CIRCOLI, "token": token}


def salva_config(token: str) -> None:
    token = token.strip()
    if not token:
        raise ErroreUtente("Err 65: codice di accesso vuoto.")
    conf.CONFIG_DB_CIRCOLI.parent.mkdir(parents=True, exist_ok=True)
    temporaneo = conf.CONFIG_DB_CIRCOLI.with_suffix(".tmp")
    temporaneo.write_text(json.dumps({"token": token}), encoding="utf-8")
    os.chmod(temporaneo, 0o600)                         # leggibile solo dall'utente del computer
    os.replace(temporaneo, conf.CONFIG_DB_CIRCOLI)      # scritto in un colpo solo


# ---------------------------------------------------------------------------
# Chiamata al portinaio
# ---------------------------------------------------------------------------
def _contesto_ssl() -> ssl.SSLContext:
    # nell'exe (PyInstaller) i certificati di sistema a volte mancano: si usano quelli di
    # certifi, che c'è già perché lo installano selenium / webdriver-manager.
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def collega(token: str) -> dict:
    # prova prima di salvare: un codice sbagliato non resta salvato (Err 60-65 -> ErroreUtente)
    token = token.strip()
    if not token:
        raise ErroreUtente("Err 65: codice di accesso vuoto.")
    stato_db = _chiama("stato", cfg={"url": conf.URL_DB_CIRCOLI, "token": token})
    salva_config(token)
    return stato_db


def _scaduto(e: BaseException) -> bool:
    """True se l'errore è un tempo scaduto (anche se urllib lo incarta in un URLError)."""
    motivo = getattr(e, "reason", e)
    return isinstance(motivo, (TimeoutError, socket.timeout)) or "timed out" in str(e).lower()


def _chiama(azione: str, cfg: dict | None = None, tentativi: int | None = None, timeout: float | None = None,
            **dati) -> dict:
    cfg = cfg or _config()
    tentativi, timeout = tentativi or TENTATIVI, timeout or TIMEOUT_S   # letti adesso, non alla definizione
    corpo = json.dumps({"token": cfg["token"], "versione": conf.VERSIONE, "azione": azione, **dati}).encode("utf-8")
    richiesta = urllib.request.Request(cfg["url"], data=corpo, method="POST",
                                       headers={"Content-Type": "application/json"})
    # Google risponde con un redirect: urllib lo segue da solo (diventa GET, come vuole Apps Script)
    for tentativo in range(1, tentativi + 1):
        try:
            with urllib.request.urlopen(richiesta, timeout=timeout, context=_contesto_ssl()) as r:
                testo = r.read().decode("utf-8")
            break
        except urllib.error.HTTPError as e:
            raise ErroreUtente(f"Err 60: il DB circoli ha risposto con errore HTTP {e.code}: "
                               f"il DB circoli è stato spostato o rimosso?") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            # tempo scaduto = Google ha ricevuto ma la risposta non arriva: si riprova, poi Err 67.
            # Qualunque altro errore (niente rete, nome non trovato, connessione rifiutata): Err 60 subito.
            if not _scaduto(e):
                raise ErroreUtente(f"Err 60: nessuna connessione a Google (rete assente?): {e}") from e
            if tentativo == tentativi:
                raise ErroreUtente(f"Err 67: Google ha ricevuto la richiesta, ma dopo {tentativi} tentativi da "
                                   f"{timeout:g} s la risposta non è arrivata.") from e

    try:
        risposta = json.loads(testo)
    except json.JSONDecodeError as e:
        # tipico: pagina di login Google -> deployment non pubblicato con accesso "Chiunque"
        raise ErroreUtente("Err 63: il DB circoli non ha risposto in JSON: "
                           "controlla che il deployment sia «App web» con accesso «Chiunque».") from e
    if not risposta.get("ok"):
        raise ErroreUtente(risposta.get("errore") or "Err 63: risposta del DB circoli senza esito.")
    return risposta


# ---------------------------------------------------------------------------
# Le quattro azioni
# ---------------------------------------------------------------------------
def cerca(nomi) -> dict[str, tuple[str, str]]:
    """Solo i circoli trovati; chiave = nome maiuscolo (come players.mappa_clubs). Regione GREZZA del foglio."""
    # None e NaN (celle vuote di pandas) non si mandano: str() li farebbe diventare "None" / "nan"
    elenco = sorted({str(n).strip() for n in nomi
                     if n is not None and not (isinstance(n, float) and n != n) and str(n).strip()})
    trovati: dict[str, tuple[str, str]] = {}
    for i in range(0, len(elenco), MAX_NOMI):
        r = _chiama("cerca", nomi=elenco[i:i + MAX_NOMI])
        trovati.update({k: (v[0], v[1]) for k, v in r["trovati"].items()})
    return trovati


def province() -> dict[str, str]:
    return _chiama("province")["province"]


def aggiungi(righe: list[tuple[str, str]]) -> dict:
    """righe = [(circolo, provincia)]. Restituisce {"aggiunti": [[c, p, r]], "gia_presenti": [...], "totale": n}."""
    return _chiama("aggiungi", righe=[[c, p] for c, p in righe])


def stato() -> dict:
    return _chiama("stato")


# contatore delle funzioni usate, IN SOTTOFONDO: è statistica, non deve mai bloccare né rallentare
# un'elaborazione. Si manda quando un'elaborazione parte (core/app.py) senza aspettare la risposta;
# se Google non risponde il +1 si perde e lo si scrive solo nel registro di avvio.
# La revoca del codice resta: tennis e beach chiamano comunque "cerca", il campionato si ferma
# dall'index (popup e schede spente).
FUNZIONI_USO = ("tennis", "beach", "campionato", "coeff_beach", "circoli")


def registra_uso(funzione: str) -> None:
    if funzione not in FUNZIONI_USO:
        raise ValueError(f"funzione sconosciuta per il contatore: {funzione!r}")   # errore di programma
    if not collegato():
        return

    def invia():
        try:
            _chiama("uso", funzione=funzione)
        except Exception as e:                      # qualunque errore: il lavoro dell'utente va avanti
            print(f"Contatore non aggiornato ({funzione}): {e}", flush=True)

    threading.Thread(target=invia, daemon=True, name=f"contatore-{funzione}").start()


# controllo del codice quando si preme Avvia (tennis, beach, campionato).
# Blocca SOLO se Google risponde "codice non valido" (Err 61, 62, 65): così un codice revocato non
# apre nemmeno Chrome. Se Google non risponde (Err 60, 63, 67) si parte lo stesso: il campionato non
# deve dipendere da Google, e tennis/beach lo ricontrollano comunque con "cerca".
# Un solo tentativo breve: al massimo VERIFICA_S secondi in più all'avvio.
VERIFICA_S = 8
BLOCCANTI = ("Err 61", "Err 62", "Err 65")


def verifica_avvio() -> bool:
    """True = codice confermato da Google; False = Google non ha risposto (si parte lo stesso).
    Solleva ErroreUtente se il codice è stato rifiutato."""
    try:
        _chiama("stato", tentativi=1, timeout=VERIFICA_S)
    except ErroreUtente as e:
        if str(e).startswith(BLOCCANTI):
            raise
        print(f"Controllo del codice non riuscito, si parte lo stesso: {e}", flush=True)
        return False
    return True
