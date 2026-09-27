"""Lavori lunghi (controllo tessere con Selenium) in background, con avanzamento in diretta via SSE.

Perche' serve un thread e non basta lo `yield` nella rotta:
  - se il controllo girasse DENTRO la richiesta POST, il browser resterebbe minuti senza risposta
    e potrebbe interrompere l'attesa (timeout);
  - se girasse DENTRO lo stream SSE (il generatore della rotta), chiudere o ricaricare la pagina
    ucciderebbe il lavoro a meta', e la riconnessione automatica di EventSource ne farebbe partire
    un SECONDO: due Chrome in parallelo sugli stessi giocatori.
  Qui invece il lavoro gira in un thread suo e scrive log e avanzamento in un oggetto `Lavoro`;
  lo stream SSE si limita a LEGGERE quell'oggetto e a mandare al browser le novita'.

    POST /tennis ──> avvia() ──> thread: main.torneo(opz, driver, lavoro.log, lavoro.avanzamento)
         │                                              │ scrive
         ▼                                              ▼
    /elaborazione/<id> <── SSE ── stream(lavoro) ── legge ── Lavoro(messaggi, fatti, totale, stato)

Un solo lavoro alla volta (un solo Chrome che interroga il sito FITP).
"""
from __future__ import annotations

import json
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Callable

from core.errori import ErroreUtente, cosa_fare

INTERVALLO = 0.3   # secondi tra due controlli dello stream
PING_OGNI = 15     # secondi di silenzio dopo cui si manda un "ping" per tenere viva la connessione
TENUTI = 20        # lavori conclusi tenuti in memoria (servono per i download)


@dataclass
class Lavoro:
    id: str
    tipo: str                          # 'tennis' | 'beach' | 'campionato' (colore e icona della pagina)
    titolo: str = ""
    # 'controllo' -> pagina di download; 'aggiornamento' (file di data/) -> si torna alla sezione
    genere: str = "controllo"
    stato: str = "in_corso"            # 'in_corso' | 'finito' | 'errore'
    messaggi: list[str] = field(default_factory=list)
    fase: str = ""
    totale: int = 0
    fatti: int = 0
    inizio: float = field(default_factory=time.time)
    inizio_fase: float = field(default_factory=time.time)
    esito: dict | None = None          # il dict restituito da main.torneo
    errore: str = ""                   # "ValueError: Err 10: ..." se si e' fermato
    dettaglio: str = ""                # traceback completo

    # Queste due si passano a main.torneo(...) come `log` e `avanzamento`.
    def log(self, messaggio) -> None:
        self.messaggi.append(str(messaggio))
        print("  ·", messaggio, flush=True)          # anche nel terminale, come da riga di comando

    def avanzamento(self, fatti: int, totale: int, fase: str = "") -> None:
        if fase != self.fase or fatti == 0:
            self.inizio_fase = time.time()
        self.fase, self.totale, self.fatti = fase, totale, fatti


_lavori: dict[str, Lavoro] = {}
_blocco = threading.Lock()


def livello(messaggio) -> str:
    """Colore di una riga di log: 'err' | 'att' | 'info'.

    Un'unica regola per la pagina in diretta e per la pagina di download (app.py la rende
    disponibile ai template come `livello_log`)."""
    t = str(messaggio)
    if t.startswith("Err"):
        return "err"
    if t.startswith("Att") or any(p in t for p in ("Scaduto", "In scadenza", "verifica manuale", "Certificato=N/D")):
        return "att"
    return "info"


def in_corso() -> Lavoro | None:
    """Il lavoro che sta girando adesso, oppure None."""
    with _blocco:
        return next((l for l in _lavori.values() if l.stato == "in_corso"), None)


def prendi(id_lavoro: str) -> Lavoro | None:
    return _lavori.get(id_lavoro)


def avvia(tipo: str, funzione: Callable[[Lavoro], dict], titolo: str = "", genere: str = "controllo") -> Lavoro:
    """Fa partire `funzione(lavoro)` in un thread e restituisce SUBITO il Lavoro.

    `funzione` deve restituire l'esito (il dict di main.torneo). Se solleva un'eccezione, il lavoro
    passa in stato 'errore' con messaggio e traceback completi: la pagina e il terminale li mostrano.
    Se c'e' gia' un lavoro in corso -> RuntimeError (le rotte controllano prima con in_corso()).
    """
    with _blocco:
        attivo = next((l for l in _lavori.values() if l.stato == "in_corso"), None)
        if attivo is not None:
            raise RuntimeError(f"C'e' gia' un'elaborazione in corso (id {attivo.id}): ne gira una alla volta.")
        _pulisci()
        lavoro = Lavoro(id=uuid.uuid4().hex[:12], tipo=tipo, titolo=titolo, genere=genere)
        _lavori[lavoro.id] = lavoro
    threading.Thread(target=_esegui, args=(lavoro, funzione), name=f"lavoro-{lavoro.id}", daemon=True).start()
    return lavoro


def _esegui(lavoro: Lavoro, funzione: Callable[[Lavoro], dict]) -> None:
    try:
        lavoro.esito = funzione(lavoro)
        lavoro.stato = "finito"                     # per ULTIMO: lo stream si fida di quest'ordine
    except ErroreUtente as e:
        # errore nei file dell'utente: messaggio e "cosa fare", senza traceback
        lavoro.errore = str(e)
        lavoro.stato = "errore"
        print(f"\n!!! Elaborazione {lavoro.id} interrotta: {e}", flush=True)
    except Exception as e:
        lavoro.errore = f"{type(e).__name__}: {e}"
        lavoro.dettaglio = traceback.format_exc()
        lavoro.stato = "errore"
        # Niente viene nascosto: traceback completo anche nel terminale.
        print(f"\n!!! Elaborazione {lavoro.id} interrotta:\n{lavoro.dettaglio}", flush=True)


def _pulisci() -> None:
    conclusi = sorted((l for l in _lavori.values() if l.stato != "in_corso"), key=lambda l: l.inizio)
    for vecchio in conclusi[:max(0, len(conclusi) - TENUTI)]:
        del _lavori[vecchio.id]


# --- Server-Sent Events ---------------------------------------------------------
def stream(lavoro: Lavoro, ultimo_id: int = 0):
    """Generatore per la rotta SSE: manda righe di log nuove, avanzamento e fine (o errore).

    `ultimo_id` = quante righe il browser ha gia' ricevuto (header Last-Event-ID, lo manda da solo
    quando si riconnette): si riparte da li', senza doppioni. Una pagina appena aperta parte da 0
    e riceve tutto lo storico.
    """
    inviati = max(0, min(int(ultimo_id), len(lavoro.messaggi)))
    ultimo_avanzamento = None
    ultimo_invio = time.time()
    yield "retry: 3000\n\n"                          # se la connessione cade il browser riprova dopo 3 s

    while True:
        # Letto PRIMA dei messaggi: _esegui cambia lo stato solo dopo l'ultima riga di log,
        # quindi se qui risulta concluso, sotto si svuotano davvero tutte le righe.
        concluso = lavoro.stato != "in_corso"

        while inviati < len(lavoro.messaggi):
            messaggio = lavoro.messaggi[inviati]
            inviati += 1
            yield _evento({"tipo": "log", "messaggio": messaggio, "livello": livello(messaggio)}, inviati)
            ultimo_invio = time.time()

        adesso = (lavoro.fatti, lavoro.totale, lavoro.fase)
        if adesso != ultimo_avanzamento:
            ultimo_avanzamento = adesso
            yield _evento(_dati_avanzamento(lavoro))
            ultimo_invio = time.time()

        if concluso:
            if lavoro.stato == "errore":
                yield _evento({"tipo": "errore", "messaggio": lavoro.errore, "dettaglio": lavoro.dettaglio,
                               "rimedio": cosa_fare(lavoro.errore)})
            else:
                yield _evento({"tipo": "fine"})
            return

        if time.time() - ultimo_invio > PING_OGNI:
            yield ": ping\n\n"                         # commento SSE: il browser lo ignora
            ultimo_invio = time.time()
        time.sleep(INTERVALLO)


def _dati_avanzamento(l: Lavoro) -> dict:
    ora = time.time()
    dati = {
        "tipo": "avanzamento",
        "fase": l.fase,
        "fatti": l.fatti,
        "totale": l.totale,
        "percentuale": round(100 * l.fatti / l.totale) if l.totale else None,
        "trascorso": round(ora - l.inizio),           # la pagina riallinea il suo orologio
    }
    if 0 < l.fatti < l.totale:
        dati["stima_residua"] = round((ora - l.inizio_fase) / l.fatti * (l.totale - l.fatti))
    return dati


def _evento(dati: dict, id_evento: int | None = None) -> str:
    testa = f"id: {id_evento}\n" if id_evento is not None else ""
    return f"{testa}data: {json.dumps(dati, ensure_ascii=False)}\n\n"
