"""App Flask del TASK menager: pagine, avvio delle elaborazioni e avanzamento in diretta (SSE).

Avvio per l'UTENTE: doppio clic su "Start TASK.app" (Mac) o "Start TASK.vbs" (Windows) -> avvia.py.
Avvio per lo SVILUPPATORE, dalla cartella del progetto (variabili d'ambiente facoltative):
    python3 core/app.py                       modalità utente: errori mostrati in errore.html
    FITP_DEBUG=1 python3 core/app.py          debugger di Flask + riavvio automatico se cambi un .py
    FITP_DRIVER_FINTO=1 python3 core/app.py   niente Selenium: certificati INVENTATI (solo prove)
    FITP_PORTA=5060 python3 core/app.py       porta diversa da conf.PORTA_GUI

Percorso di un torneo:
    /tennis (GET modulo, POST avvio) -> /elaborazione/<id> -> /stream_elaborazione/<id> (SSE)
    -> /download/<id> -> /get_file/<id>
"""
#Comm. Claude:  docstring: aggiornati i nomi dei lanciatori (Start TASK.app / Start TASK.vbs)
import io
import os
import secrets
import sys
import threading
import time  #Comm. Claude:  serve al watchdog che chiude il programma quando la pagina si chiude
import traceback
import webbrowser
from datetime import datetime
from pathlib import Path

# con `python3 core/app.py` nel path c'è solo core/: aggiungo la cartella del progetto
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from flask import Flask, Response, abort, flash, redirect, render_template, request, send_file, session, url_for
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

import pdfplumber

from core import conf, lavori
from core.errori import ErroreUtente, codici_non_documentati, cosa_fare
from processor import campionato as _cs
from processor import data_update
from processor import file_utente as _fu
from processor import main as _main

app = Flask(__name__, template_folder=str(conf.HTML_DIR), static_folder=str(conf.STATIC_DIR))
app.secret_key = secrets.token_hex(16)                  # per session e flash; nuovo a ogni avvio
app.jinja_env.globals["livello_log"] = lavori.livello   # colori del registro, regola unica


def _migliaia(numero) -> str:
    """14433 -> '14.433' (separatore delle migliaia all'italiana)."""
    return f"{int(numero):,}".replace(",", ".")


app.jinja_env.filters["migliaia"] = _migliaia

conf.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
conf.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# senza codici_errori.csv le pagine d'errore non hanno il "cosa fare": ci si ferma subito
if not conf.CODICI_ERRORI.is_file():
    raise FileNotFoundError(f"Manca il file dei codici d'errore: {conf.CODICI_ERRORI}")

# modalità utente (predefinita): pagine d'errore semplici; sviluppatore: FITP_DEBUG=1
DEBUG = os.environ.get("FITP_DEBUG") == "1"


if DEBUG:
    for codice in codici_non_documentati():                 # promemoria per chi sviluppa
        print(f"ATTENZIONE: il codice «{codice}» è usato nel programma ma manca in codici_errori.csv")


# Errore nei file/scelte dell'utente (in ogni modalità): messaggio + "cosa fare", si torna al modulo.
# coll: core.errori (ErroreUtente, codici_errori.csv) | html: base.html (messaggio in cima alla pagina)
@app.errorhandler(ErroreUtente)
def _errore_utente(errore):
    print(f"  · {errore}", flush=True)
    flash({"testo": str(errore), "rimedio": cosa_fare(errore)}, "error")
    return redirect(request.referrer or url_for("index"))


# Solo modalità utente: un crash in una rotta mostra errore.html con messaggio e traceback.
# coll: nessuno | html: errore.html
if not DEBUG:
    @app.errorhandler(Exception)
    def _pagina_errore(errore):
        if isinstance(errore, HTTPException):          # 404 e simili restano quello che sono
            return errore
        dettaglio = "".join(traceback.format_exception(type(errore), errore, errore.__traceback__))
        print(f"\n!!! Errore nella pagina {request.path}:\n{dettaglio}", flush=True)   # anche nel terminale
        return render_template("errore.html", messaggio=f"{type(errore).__name__}: {errore}",
                               dettaglio=dettaglio, rimedio=cosa_fare(errore)), 500


# Ogni risposta porta un'intestazione nascosta: avvia.py la usa per capire se l'app è già aperta.
# coll: avvia.fitp_gia_aperto
@app.after_request
def _firma(risposta):
    risposta.headers["X-FITP-Manager"] = "1"
    return risposta


#Comm. Claude:  blocco nuovo (heartbeat + watchdog). Sta qui e non in avvia.py perché questo è il processo
#Comm. Claude:  che gira nella .venv e serve le pagine. Logica: la pagina manda un ping ogni 2 s; quando si
#Comm. Claude:  chiude manda un "beacon" di chiusura. Il watchdog spegne il processo se (a) dopo il beacon non
#Comm. Claude:  arriva un nuovo ping entro ATTESA_DOPO_CHIUSURA (cambiare pagina fa partire anch'esso il beacon,
#Comm. Claude:  ma la pagina nuova pinga subito), oppure (b) non arrivano ping da SILENZIO_MASSIMO secondi:
#Comm. Claude:  75 s e non 6 perché Chrome rallenta i timer delle schede in background fino a 1 volta al minuto.
#Comm. Claude:  Non spegne mai durante un'elaborazione (lavori.in_corso), per non perdere il lavoro.
ATTESA_DOPO_CHIUSURA = 5   # s tra il beacon di chiusura e lo spegnimento, se nessuna pagina nuova pinga
SILENZIO_MASSIMO = 75      # s senza ping (browser chiuso di colpo, scheda congelata...)
_ultimo_ping = time.time()        # parte da ora: il browser ha SILENZIO_MASSIMO s per aprire la prima pagina
_chiusura_richiesta = None        # istante dell'ultimo beacon di chiusura


# Ping periodico della pagina: finché arriva il programma resta acceso.
# coll: base.html (script) -> _heartbeat -> _watchdog
@app.route("/_heartbeat", methods=["POST"])
def _heartbeat():
    global _ultimo_ping
    _ultimo_ping = time.time()
    return "", 204


# Beacon inviato dalla pagina quando si chiude o si cambia pagina.
# coll: base.html (pagehide) -> _chiudi -> _watchdog
@app.route("/_chiudi", methods=["POST"])
def _chiudi():
    global _chiusura_richiesta
    _chiusura_richiesta = time.time()
    return "", 204


def _watchdog() -> None:
    """Thread di sfondo: spegne il processo quando nessuna pagina di TASK è più aperta."""
    while True:
        time.sleep(1)
        adesso = time.time()
        # confronto i tempi invece di azzerare: un ping arrivato DOPO il beacon annulla la chiusura
        pagina_chiusa = (_chiusura_richiesta is not None and _ultimo_ping < _chiusura_richiesta
                         and adesso - _chiusura_richiesta > ATTESA_DOPO_CHIUSURA)
        pagina_muta = adesso - _ultimo_ping > SILENZIO_MASSIMO
        if (pagina_chiusa or pagina_muta) and lavori.in_corso() is None:
            print("\nPagina chiusa: TASK si spegne.", flush=True)
            os._exit(0)   # esce subito da tutti i thread (anche quelli del server)


# In ogni pagina: link "Elaborazione in corso" nella testata finché un lavoro gira.
# coll: lavori.in_corso | html: base.html
@app.context_processor
def _lavoro_attivo():
    return {"lavoro_attivo": lavori.in_corso()}


# =============================================================================
# Aiuti per leggere i form. SECONDA barriera: il browser ha già controllato tutto,
# ma una richiesta può arrivare anche senza passare dal browser.
# =============================================================================
def _scelta(campo: str, ammessi: tuple) -> str:
    """Valore di un radio o di una tendina: deve essere uno di quelli previsti."""
    valore = request.form.get(campo)
    if valore not in ammessi:
        raise ErroreUtente(f"Err 13: valore non valido per '{campo}': {valore!r} (ammessi: {', '.join(ammessi)})")
    return valore


def _data(campo: str) -> datetime:
    """Il calendario HTML manda sempre AAAA-MM-GG, qualunque sia la lingua del browser."""
    return datetime.strptime(request.form[campo], "%Y-%m-%d")


def _gg_mm_aaaa(data: datetime) -> str:
    return data.strftime("%d/%m/%Y")                     # formato che vuole fitp_driver


def _quota(campo: str) -> float:
    valore = float(request.form[campo])
    if valore < 0:
        raise ErroreUtente(f"Err 13: '{campo}' non può essere negativa ({valore}).")
    return valore


def _nuova_cartella() -> Path:
    """Una sottocartella di upload/ per ogni invio: i file di invii diversi non si sovrascrivono."""
    cartella = conf.UPLOAD_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{secrets.token_hex(3)}"
    cartella.mkdir(parents=True)
    return cartella


def _salva(file_caricato, cartella: Path, estensioni: tuple) -> Path:
    """Salva un file caricato mantenendo il nome (ripulito): il nome del PDF contiene la serie."""
    nome = secure_filename(file_caricato.filename or "")
    if not nome or Path(nome).suffix.lower() not in estensioni:
        raise ErroreUtente(f"Err 12: file non valido {file_caricato.filename!r}: serve {' o '.join(estensioni)}")
    percorso = cartella / nome
    file_caricato.save(percorso)
    return percorso


def _file_mancanti(sezione: str) -> list:
    """File di data/ indispensabili per la sezione (conf.FILE_NECESSARI) che non ci sono."""
    return [p.name for p in conf.FILE_NECESSARI[sezione] if not Path(p).is_file()]


def _avviso_mancanti(sezione: str) -> bool:
    """Mostra in cima alla pagina quali file mancano in data/. True se ne manca almeno uno."""
    mancanti = _file_mancanti(sezione)
    if mancanti:
        flash(f"Mancano in {conf.DB_DIR}: {', '.join(mancanti)}. "
              f"Senza questi file l'elaborazione non può partire.", "error")
    return bool(mancanti)


def _occupato():
    """Se sta già girando un'elaborazione, rimanda a quella invece di avviarne una seconda."""
    attivo = lavori.in_corso()
    if attivo is None:
        return None
    flash("C'è già un'elaborazione in corso: aspetta che finisca prima di avviarne un'altra.", "warning")
    return redirect(url_for("elaborazione", id_lavoro=attivo.id))


# =============================================================================
# Avvio del lavoro in background
# =============================================================================
def _con_driver(lavoro: lavori.Lavoro, esegui):
    """Apre il browser del controllo tessere, esegue, e lo chiude SEMPRE (anche se crasha)."""
    if os.environ.get("FITP_DRIVER_FINTO") == "1":
        from core.driver_finto import DriverFinto as Driver
        lavoro.log("Att. 00: driver FINTO attivo (FITP_DRIVER_FINTO=1): certificati e cittadinanze sono INVENTATI.")
    else:
        from core.fitp_driver import TesseraDriver as Driver
        lavoro.log("Avvio il browser per il controllo delle tessere…")
    with Driver() as driver:
        return esegui(driver)


def _avvia(tipo: str, opz, titolo: str):
    """Lancia main.torneo(opz) in un thread e rimanda subito alla pagina di avanzamento."""
    def lavoro_vero(lavoro: lavori.Lavoro) -> dict:
        return _con_driver(lavoro, lambda driver: _main.torneo(
            opz, driver=driver, log=lavoro.log, avanzamento=lavoro.avanzamento))

    lavoro = lavori.avvia(tipo, lavoro_vero, titolo)
    return redirect(url_for("elaborazione", id_lavoro=lavoro.id))


# =============================================================================
# Rotte: pagine e form
# =============================================================================

# Home: tre schede per scegliere tennis, beach tennis o campionato a squadre.
# coll: nessuno | html: index.html
@app.route("/")
def index():
    return render_template("index.html")


# Torneo tennis (singolare o doppio): GET mostra il modulo, POST avvia il controllo tessere in background.
# coll: file_utente.leggi_iscritti | lavori -> main.torneo -> players.player_list (circoli) -> fitp_driver | main -> players.forma_coppie (doppio) -> ranking | main -> contatti, live_score, excel_sheets
# coll (scheda circoli): data_update.stato_circoli
# html: tennis.html (+ _form_torneo.html, _circoli.html) -> elaborazione.html -> download.html
@app.route("/tennis", methods=["GET", "POST"])
def tennis():
    return _pagina_torneo("tennis")


# Torneo beach: come il tennis, in più coefficienti beach ed Entry List singolare/doppio.
# coll: file_utente.leggi_iscritti | lavori -> main.torneo -> players (player_list, entry_beach) -> ranking, fitp_driver | main -> contatti, live_score, excel_sheets
# coll (scheda coefficienti): data_update.stato_coeff_beach | (scheda circoli): data_update.stato_circoli
# html: beach.html (+ _form_torneo.html, _circoli.html) -> elaborazione.html -> download.html
@app.route("/beach", methods=["GET", "POST"])
def beach():
    return _pagina_torneo("beach")


def _pagina_torneo(sport: str):
    """Parte comune di tennis e beach: stessi campi, cambia solo `sport` (e il doppio nel beach)."""
    occupato = _occupato()
    if occupato:
        return occupato
    if request.method == "GET":
        _avviso_mancanti(sport)
        contesto = {"circoli": data_update.stato_circoli()}
        if sport == "beach":
            _esito_aggiornamento(request.args.get("aggiornato"))
            contesto["coeff"] = data_update.stato_coeff_beach()
        return render_template(f"{sport}.html", **contesto)
    if _file_mancanti(sport):                            # file di data/ mancanti: non si parte,
        return redirect(url_for(sport))                  # la pagina GET mostra quali mancano

    # 1) campi del form (prima di salvare qualunque file)       campo HTML -> campo TypeTorneo
    inizio, fine = _data("data_inizio"), _data("data_fine")   # data_inizio / data_fine
    if fine < inizio:
        raise ErroreUtente("Err 14: la data di fine torneo è prima della data di inizio.")
    doppio = _scelta("disciplina", ("singolo", "doppio")) == "doppio"                         # doppio
    con_quota = _scelta("con_quota", ("si", "no")) == "si"    # con_quota
    gen_ls = _scelta("gen_ls", ("si", "no")) == "si"          # gen_ls
    gen_prog = _scelta("gen_prog", ("si", "no")) == "si"      # gen_prog

    # 2) file iscritti -> upload/<data_ora_codice>/
    cartella = _nuova_cartella()
    iscritti = _salva(request.files["file_iscritti"], cartella, (".xlsx", ".xls"))
    _fu.leggi_iscritti(iscritti, doppio=doppio)
    base = f"{iscritti.stem}_{sport}{'_doppio' if doppio else ''}_{cartella.name}"

    opz = _main.TypeTorneo(
        file_iscritti=str(iscritti),
        file_output=str(conf.OUTPUT_DIR / f"{base}.xlsx"),
        sport=sport,
        doppio=doppio,
        data_inizio=_gg_mm_aaaa(inizio),
        data_fine=_gg_mm_aaaa(fine),
        nome_torneo=request.form.get("nome_torneo", "").strip(),
        con_quota=con_quota,
        quota_under=_quota("quota_under") if con_quota else 0.0,     # campo spento se quota = no
        quota_over=_quota("quota_over") if con_quota else 0.0,
        gen_ls=gen_ls,
        ls_event=_scelta("ls_event", ("M", "F")) if gen_ls else None,  # campo spento se live score = no
        ls_path=str(conf.OUTPUT_DIR / f"{base}_LiveScore.csv"),
        gen_prog=gen_prog,
    )
    nome_sport = ("Tennis" if sport == "tennis" else "Beach tennis") + (" doppio" if doppio else "")
    return _avvia(sport, opz, f"{nome_sport} · {iscritti.name}")


def _esito_aggiornamento(id_lavoro):
    """Messaggio verde con il riepilogo di un aggiornamento dei dati appena concluso."""
    lavoro = lavori.prendi(id_lavoro) if id_lavoro else None
    if lavoro and lavoro.genere == "aggiornamento" and lavoro.stato == "finito":
        e = lavoro.esito
        flash(f"Coefficienti beach aggiornati: {_migliaia(e['righe'])} giocatori "
              f"({_migliaia(e['uomini'])} uomini, {_migliaia(e['donne'])} donne). "
              f"La versione precedente è in data/archivio/.", "success")


# Aggiorna i coefficienti beach: salva il PDF unito (o i due PDF FITP) e lo converte in background.
# coll: lavori -> data_update.aggiorna_coeff_beach -> pdfplumber | html: beach.html -> elaborazione.html -> beach.html
@app.route("/beach/coefficienti", methods=["POST"])
def aggiorna_coeff_beach():
    occupato = _occupato()                     # anche per sicurezza: mai sostituire il file mentre un torneo lo usa
    if occupato:
        return occupato
    caricati = [f for f in request.files.getlist("pdf_classifiche") if f.filename]
    if not 1 <= len(caricati) <= 2:
        raise ErroreUtente(f"Err 46: {len(caricati)} file caricati: serve il PDF unito oppure i due PDF FITP.")
    cartella = _nuova_cartella()
    pdf = []
    for n, f in enumerate(caricati, start=1):  # una sottocartella per file: due nomi uguali non si sovrascrivono
        (cartella / str(n)).mkdir()
        pdf.append(_salva(f, cartella / str(n), (".pdf",)))
    lavoro = lavori.avvia(
        "beach",
        lambda l: data_update.aggiorna_coeff_beach(pdf, log=l.log, avanzamento=l.avanzamento),
        titolo="Aggiornamento coefficienti beach",
        genere="aggiornamento",
    )
    return redirect(url_for("elaborazione", id_lavoro=lavoro.id))


# Circoli non trovati in un torneo: scarica l'Excel da compilare (provincia a tendina).
# coll: lavori.prendi -> esito["circoli_mancanti"] (main.torneo) | data_update.province_circoli -> file_utente.modulo_circoli
@app.route("/circoli/da_mappare/<id_lavoro>")
def circoli_da_mappare(id_lavoro):
    lavoro = lavori.prendi(id_lavoro)
    if lavoro is None or not (lavoro.esito or {}).get("circoli_mancanti"):
        abort(404, "Nessun circolo da mappare: il programma è stato riavviato?")
    ancora = data_update.circoli_non_presenti(lavoro.esito["circoli_mancanti"])   # tolti quelli già aggiunti
    if not ancora:
        abort(404, "I circoli di questa elaborazione sono già tutti nel file dei circoli.")
    contenuto = _fu.modulo_circoli(ancora, data_update.province_circoli())
    return send_file(io.BytesIO(contenuto), as_attachment=True,
                     download_name=f"circoli_da_mappare_{datetime.now():%Y%m%d_%H%M}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# File dei circoli compilato: righe aggiunte in fondo a circolo_regioni.csv, poi si torna alla pagina.
# coll: data_update.aggiungi_circoli -> file_utente.leggi_circoli_compilati | html: _circoli.html (download, tennis, beach)
@app.route("/circoli/aggiungi", methods=["POST"])
def aggiungi_circoli():
    compilato = _salva(request.files["file_circoli"], _nuova_cartella(), (".xlsx",))
    avvisi: list[str] = []
    esito = data_update.aggiungi_circoli(compilato, log=avvisi.append)   # Err 30/48/49/51 -> ErroreUtente
    for riga in avvisi:
        if riga.startswith("Att."):
            flash({"testo": riga, "rimedio": cosa_fare(riga)}, "warning")
    n, vuoti = len(esito["aggiunti"]), esito["senza_provincia"]
    if n:
        nomi = ", ".join(c for c, _p, _r in esito["aggiunti"])
        flash(f"{'Aggiunto 1 circolo' if n == 1 else f'Aggiunti {n} circoli'} a {esito['file']}: {nomi}. "
              f"Rilancia l'elaborazione per avere provincia e regione nel foglio Giocatori.", "success")
    else:
        flash(f"Nessun circolo nuovo da aggiungere a {esito['file']}.", "warning")
    if vuoti:
        flash("1 circolo lasciato senza provincia: non aggiunto." if vuoti == 1
              else f"{vuoti} circoli lasciati senza provincia: non aggiunti.", "message")
    return redirect(request.referrer or url_for("index"))


# Campionato fase 1: salva e controlla PDF e file SGAT, legge le squadre dal PDF.
# coll: file_utente.leggi_sgat | main.analizza_pdf_campionato -> campionato.leggi_lista (pdfplumber) | html: campionato.html fase 1 -> fase 2
@app.route("/campionato", methods=["GET", "POST"])
def campionato():
    occupato = _occupato()
    if occupato:
        return occupato
    if request.method == "GET":
        return render_template("campionato.html")

    cartella = _nuova_cartella()
    pdf = _salva(request.files["pdf_lista"], cartella, (".pdf",))
    sgat = _salva(request.files["file_sgat"], cartella, (".xlsx", ".xls"))

    avvisi: list[str] = []
    sgat_letto = _fu.leggi_sgat(sgat, log=avvisi.append)            # ErroreUtente -> messaggio e si torna qui
    try:
        with pdfplumber.open(pdf) as documento:
            len(documento.pages)                                   # solo "si apre?": gli errori veri devono emergere
    except Exception as e:
        raise ErroreUtente(f"Err 28: il PDF «{pdf.name}» non si apre ({type(e).__name__}): è danneggiato o non è un PDF.") from e
    info = _main.analizza_pdf_campionato(str(pdf))
    for avviso in avvisi:
        flash({"testo": avviso, "rimedio": cosa_fare(avviso)}, "warning")
    # Solo i percorsi in sessione: la lista dei giocatori è troppo grande per il cookie.
    session["cs"] = {"pdf": str(pdf), "sgat": str(sgat)}
    return render_template(
        "campionato.html",
        sgat_righe={ruolo: len(df) for ruolo, df in sgat_letto.items()},
        squadre=info.get("squadre", []),                   # [] se il PDF non ha giocatori: la pagina lo dice
        campionato=info.get("campionato"),
        n_giocatori=info.get("numero_giocatori_totali", 0),
        nome_pdf=pdf.name,
        nome_sgat=sgat.name,
    )


# Scarica il modello Excel del file SGAT (fogli Casa/Ospite con le colonne giuste).
# coll: file_utente.modello_sgat (openpyxl) | html: link in campionato.html fase 1
@app.route("/campionato/modello_sgat")
def modello_sgat():
    return send_file(io.BytesIO(_fu.modello_sgat()), as_attachment=True, download_name="modello_SGAT_campionato.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# Campionato fase 2: verifica casa, ospite e data, poi avvia il controllo tessere.
# coll: campionato.leggi_lista | lavori -> main.torneo -> campionato.foglio_cs (file_utente.leggi_sgat) -> players.campionato -> fitp_driver
# html: campionato.html fase 2 -> elaborazione.html -> download.html
@app.route("/campionato/genera", methods=["POST"])
def campionato_genera():
    occupato = _occupato()
    if occupato:
        return occupato
    cs = session.get("cs")
    if not cs or not Path(cs["pdf"]).is_file() or not Path(cs["sgat"]).is_file():
        flash("I file caricati non sono più disponibili (il programma è stato riavviato?): caricali di nuovo.", "warning")
        return redirect(url_for("campionato"))

    # Rileggo il PDF (pochi secondi) e controllo le scelte contro le squadre VERE della lista.
    lista = _cs.leggi_lista(cs["pdf"])
    squadre = tuple(sorted({g.squadra for g in lista if g.squadra}))
    casa = _scelta("squadra_casa", squadre)                   # squadra_casa
    ospite = _scelta("squadra_ospite", squadre)               # squadra_ospite
    if casa == ospite:
        raise ErroreUtente("Err 15: squadra di casa e squadra ospite sono la stessa.")
    data = _data("data_incontro")                             # data_inizio (una sola data)

    nome = secure_filename(f"CS_{casa}_vs_{ospite}_{datetime.now():%Y%m%d_%H%M%S}.xlsx")
    opz = _main.TypeTorneo(
        file_iscritti=cs["sgat"],
        file_output=str(conf.OUTPUT_DIR / nome),
        cs=True,
        squadra_casa=casa,
        squadra_ospite=ospite,
        lista_pdf=lista,
        data_inizio=_gg_mm_aaaa(data),
    )
    return _avvia("campionato", opz, f"Campionato · {casa} – {ospite}")


# =============================================================================
# Rotte: elaborazione in diretta e download
# =============================================================================

# Pagina di avanzamento: barra, fase e registro in diretta di un'elaborazione.
# coll: lavori.prendi | html: elaborazione.html + static/app.js (blocco 8, EventSource)
@app.route("/elaborazione/<id_lavoro>")
def elaborazione(id_lavoro):
    lavoro = lavori.prendi(id_lavoro)
    if lavoro is None:
        abort(404, "Elaborazione non trovata: il programma è stato riavviato?")
    return render_template("elaborazione.html", lavoro=lavoro)


# Flusso SSE per la pagina: righe di log, avanzamento, poi fine oppure errore.
# coll: lavori.stream (legge il Lavoro che il thread sta scrivendo) | js: EventSource in app.js
@app.route("/stream_elaborazione/<id_lavoro>")
def stream_elaborazione(id_lavoro):
    lavoro = lavori.prendi(id_lavoro)
    if lavoro is None:
        abort(404)                          # EventSource smette di riprovare e la pagina lo segnala
    ultimo = int(request.headers.get("Last-Event-ID") or 0)   # righe già ricevute (riconnessione)
    return Response(lavori.stream(lavoro, ultimo), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# Esito finale: download e registro, pagina d'errore, o ritorno alla sezione (aggiornamenti).
# coll: lavori.prendi (esito di main.torneo), data_update.circoli_non_presenti | html: download.html (+ _circoli.html) oppure errore.html
@app.route("/download/<id_lavoro>")
def download(id_lavoro):
    lavoro = lavori.prendi(id_lavoro)
    if lavoro is None:
        return render_template("download.html", file_ready=False)
    if lavoro.stato == "in_corso":
        return redirect(url_for("elaborazione", id_lavoro=id_lavoro))
    if lavoro.stato == "errore":
        return render_template("errore.html", messaggio=lavoro.errore, dettaglio=lavoro.dettaglio,
                               rimedio=cosa_fare(lavoro.errore)), 500
    if lavoro.genere == "aggiornamento":                 # niente da scaricare: si torna alla sezione
        return redirect(url_for(lavoro.tipo, aggiornato=lavoro.id))
    mancanti = lavoro.esito.get("circoli_mancanti")
    return render_template("download.html", file_ready=True, esito=lavoro.esito, messaggi=lavoro.messaggi,
                           tema=lavoro.tipo, id_lavoro=lavoro.id,
                           circoli_mancanti=None if mancanti is None else data_update.circoli_non_presenti(mancanti))


# Invia il file Excel, oppure il CSV del Live Score con ?tipo=live_score.
# coll: lavori.prendi -> esito["file_output"] / esito["live_score"]["file"] scritti da main.torneo
@app.route("/get_file/<id_lavoro>")
def get_file(id_lavoro):
    lavoro = lavori.prendi(id_lavoro)
    if lavoro is None or lavoro.esito is None:
        abort(404, "File non trovato: il programma è stato riavviato?")
    if request.args.get("tipo") == "live_score":
        return send_file(lavoro.esito["live_score"]["file"], as_attachment=True)
    return send_file(lavoro.esito["file_output"], as_attachment=True)


if __name__ == "__main__":
    if os.environ.get("FITP_DRIVER_FINTO") == "1":
        print("\n" + "!" * 72 + "\n  ATTENZIONE: driver FINTO attivo. I controlli delle tessere sono INVENTATI.\n" + "!" * 72 + "\n")
    porta = int(os.environ.get("FITP_PORTA") or conf.PORTA_GUI)
    indirizzo = f"http://127.0.0.1:{porta}"
    # Apro il browser di sistema una volta sola: con debug Flask lancia un secondo processo
    # (quello con WERKZEUG_RUN_MAIN) che si riavvia a ogni modifica dei .py; il browser lo apre il primo.
    if not os.environ.get("WERKZEUG_RUN_MAIN"):
        threading.Timer(1.5, lambda: webbrowser.open(indirizzo)).start()
    print(f"FITP Manager su {indirizzo}  ({'modalità sviluppatore' if DEBUG else 'modalità utente'})", flush=True)
    if not DEBUG:
        # modalità utente: nella finestra solo i messaggi del programma, niente log di Flask
        import logging
        import flask.cli
        logging.getLogger("werkzeug").setLevel(logging.ERROR)
        flask.cli.show_server_banner = lambda *args, **kwargs: None
    #Comm. Claude:  watchdog solo nel processo che serve davvero le pagine: con debug Flask lancia un processo
    #Comm. Claude:  padre (solo reloader, non riceve ping) e un figlio con WERKZEUG_RUN_MAIN che serve le pagine.
    if not DEBUG or os.environ.get("WERKZEUG_RUN_MAIN"):
        threading.Thread(target=_watchdog, daemon=True).start()
    # ATTENZIONE (solo FITP_DEBUG=1): se salvi un .py mentre un'elaborazione gira, Flask si riavvia e la perde.
    app.run(host="127.0.0.1", port=porta, debug=DEBUG, threaded=True)
