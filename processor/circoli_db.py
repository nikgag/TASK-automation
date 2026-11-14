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

Errori (tutti ErroreUtente, messaggio "Err NN: ..." come nel resto dell'app):
  Err 60 rete / portinaio non raggiungibile   Err 61-64 rifiutato dal portinaio
  Err 65 DB non collegato su questo computer
Niente copia locale: senza rete TASK non lavora comunque (driver FITP), quindi si ferma subito.
"""
from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request

from core import conf
from core.errori import ErroreUtente

TIMEOUT_S = 30
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


def _chiama(azione: str, cfg: dict | None = None, **dati) -> dict:
    cfg = cfg or _config()
    corpo = json.dumps({"token": cfg["token"], "versione": conf.VERSIONE, "azione": azione, **dati}).encode("utf-8")
    richiesta = urllib.request.Request(cfg["url"], data=corpo, method="POST",
                                       headers={"Content-Type": "application/json"})
    # Google risponde con un redirect: urllib lo segue da solo (diventa GET, come vuole Apps Script)
    try:
        with urllib.request.urlopen(richiesta, timeout=TIMEOUT_S, context=_contesto_ssl()) as r:
            testo = r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raise ErroreUtente(f"Err 60: il DB circoli ha risposto con errore HTTP {e.code}: "
                           f"il DB circoli è stato spostato o rimosso?") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ErroreUtente(f"Err 60: DB circoli non raggiungibile (rete assente?): {e}") from e

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
