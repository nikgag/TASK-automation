import os    #Comm. Claude:  os e sys (libreria standard) servono per i percorsi dell'exe; avvia.py può ancora importare conf
import sys
from pathlib import Path

## contenitore di costanti e percorsi di configurazione
CD_DIR = Path.home()
# percorsi assoluti dalla cartella del progetto: funzionano da qualsiasi cartella si lanci python
BASE_DIR = Path(__file__).resolve().parent.parent

#Comm. Claude:  nell'exe (PyInstaller) i file del programma stanno nella cartella d'installazione, che l'utente
#Comm. Claude:  non deve toccare, e i dati che l'app MODIFICA (circoli aggiunti, coefficienti, output, upload) non
#Comm. Claude:  possono stare lì. Quindi due radici: RISORSE_DIR (sola lettura, dentro l'exe) e DATI_DIR (scrivibile,
#Comm. Claude:  una per utente). Da sorgente (python core/app.py) coincidono con la cartella del progetto: nulla cambia.
CONGELATO = getattr(sys, "frozen", False)             # True dentro l'exe
if CONGELATO:
    RISORSE_DIR = Path(sys._MEIPASS)                  # <installazione>/_internal
    if sys.platform == "win32":
        DATI_DIR = Path(os.environ["LOCALAPPDATA"]) / "TASK"         # C:/Users/<utente>/AppData/Local/TASK
    elif sys.platform == "darwin":
        DATI_DIR = Path.home() / "Library" / "Application Support" / "TASK"
    else:
        DATI_DIR = Path.home() / ".local" / "share" / "TASK"
else:
    RISORSE_DIR = DATI_DIR = BASE_DIR
DATI_INIZIALI_DIR = RISORSE_DIR / "data"              # nell'exe: copie di partenza, copiate in DB_DIR al primo avvio

DB_DIR = DATI_DIR / 'data'
OUTPUT_DIR = DATI_DIR / 'output'
# temp/ contiene i vecchi HTML, non usati
HTML_DIR = RISORSE_DIR / 'templates'
STATIC_DIR = RISORSE_DIR / 'static'
UPLOAD_DIR = DATI_DIR / 'upload'

# codici d'errore con causa e "cosa fare" (si apre con Excel, separatore ;)
CODICI_ERRORI = RISORSE_DIR / "codici_errori.csv"

# non 5000: sui Mac recenti è occupata da AirPlay Receiver
PORTA_GUI = 5050

# #HTML
# INDEX = HTML_DIR / 'index.html'
# UPLOAD = HTML_DIR / 'upload.html'
# DOWNLOAD = HTML_DIR / 'download.html'


# DataBase FITP
DB_CLUBS = DB_DIR / "circolo_regioni.csv"
DB_COEF_BT = DB_DIR / "coeff_beach.csv"
ENTRY_BT = DB_DIR / "mod_el.xlsx"
PROGRAMMAZIONE = DB_DIR / "mod_prog.xlsx"

# data/archivio: copia della versione precedente prima di ogni aggiornamento; registro: quando e da cosa
ARCHIVIO_DIR = DB_DIR / "archivio"
REGISTRO_AGGIORNAMENTI = DB_DIR / "aggiornamenti.json"
MESI_VALIDITA_COEFF_BT = 6

# file di data/ indispensabili per sezione: le pagine avvisano all'apertura se ne manca uno
FILE_NECESSARI = {
    "tennis": (DB_CLUBS,),
    "beach": (DB_CLUBS, DB_COEF_BT, ENTRY_BT),
    "campionato": (),
}

# Link per driver tessere
FITP_TESSERA_BASE_URL = "https://management.federtennis.it/vt"
FITP_TESSERA_QUERY = {"y": "CT"}     

#REGIONI ITALIANE
REGIONI_ITALIANE = [
    "Abruzzo", "Basilicata", "Bolzano", "Calabria", "Campania", "Emilia",
    "Friuli", "Lazio", "Liguria", "Lombardia", "Marche", "Molise",
    "Piemonte", "Puglia", "Sardegna", "Sicilia", "Toscana", "Trento", "Umbria",
    "VDA", "Veneto", "ND",
] 
# ---   CAMPIONATO A SQUADRE ----

DIR_PDF_CS = UPLOAD_DIR / "campionati"

INTESTAZIONI= {"Squadra", "Tipo Palle", "Indirizzo Campi", "Città Campi", "Superficie", "Campo Riserva", "Superficie campo principale", "Superficie Campo Riserva"}


# --- profili di colonne -------------------------------------------------------
# Un campo dell'Iscritto -> tutte le intestazioni con cui il PDF puo' chiamarlo.
# E' l'UNICO punto da toccare quando la FITP rinomina una colonna.
CAMPI: dict[str, tuple[str, ...]] = {
    "cognome": ("cognome",),
    "nome": ("nome",),
    "rank": ("classifica", "class.", "class"),
    "settore_eta": ("sett. età", "settore età", "sett.età", "settore eta", "sett. eta"),
    "variato": ("variato",),
    "vivaio": ("vivaio",),
    "nat": ("nazionalità", "nazionalita"),
    "schieramento": ("schieramento playoff - playout", "schieramento play off - play out",
                     "schieramento playoff-playout", "schieramento"),
    "rank_intl": ("atp 1-500", "wta 1-500"),
    "rank_intl_oltre": ("atp 501>", "wta 501>", "atp 501 >", "wta 501 >"),
    "numero": ("n.", "numero"),
    "tessera": ("num. tessera", "tessera", "n. tessera"),
    "nata": ("data di nascita", "data nascita", "nato/a il"),
}


# --- COLORI / STILE (usati da excel_style.py) ---------------------------------
COLORE_HEADER = "ADD8E6"        # azzurro chiaro (torneo/beach)
COLORE_HEADER_CAMPIONATO = "4F81BD"  # blu (campionato a squadre)
COLORE_VERDE = "C6EFCE"         # corrispondenza SI
COLORE_ROSSO = "FFC7CE"         # corrispondenza NO
COLORE_LINK = "0000FF"          # blu hyperlink
LARGHEZZA_COLONNA_DEFAULT = 20

# QUOTE FITP (VARIANO DI ANNO IN ANNO) 
CATEGORIE_UNDER = ["U10", "U12", "U14", "U16"]
QUOTA_FIT_UNDER = 4.5
QUOTA_FIT_OVER = 9.0

# non usato: ordina_tennis / ordina_beach non esistono (e conf.py non può importare da processor/)
# # Mappi lo sport alle funzioni specifiche o ai parametri che deve usare
# PIPELINE_SPORT = {
#     "tennis": {
#         "usa_coefficiente": False,
#         "colonna_squadra": "Numero Squadra",
#         "funzione_ordinamento": ordina_tennis
#     },
#     "beach": {
#         "usa_coefficiente": True,
#         "colonna_squadra": "Squadra Beach",
#         "funzione_ordinamento": ordina_beach
#     }
# }
#
# def configura_pipeline(sport: str):
#     sport_key = str(sport).strip().lower()
#
#     if sport_key not in PIPELINE_SPORT:
#         raise ValueError(f"Sport sconosciuto: {sport}")
#
#     return PIPELINE_SPORT[sport_key]