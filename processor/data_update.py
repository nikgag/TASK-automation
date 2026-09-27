## script per aggiornate il DB in automatico:
# coeff beach cambiano ogni 6 mesi (gennaio e luglio)
# la denominazione dei circoli cambia spesso è necessario aggiornare la lista -- demo
"""Aggiornamento dei file di riferimento in data/ a partire dai PDF pubblicati dalla FITP.

COEFFICIENTI BEACH (data/coeff_beach.csv) = UNIONE della classifica FEMMINILE e di quella MASCHILE.
  aggiorna_coeff_beach(pdf)   pdf = il PDF unito, oppure la lista dei due PDF FITP (li unisce lui)
  stato_coeff_beach()         cosa mostrare nella pagina beach

Perché si legge il TESTO e non le TABELLE del PDF (provato sui PDF FITP di luglio 2026):
  con extract_tables() le società lunghe "traboccano" nelle colonne accanto e i caratteri si
  mescolano ("( NON AFFILIATO…" + "4.NC" -> "AFF4IL.NIACTO P"): è da lì che venivano le righe
  sporche del vecchio CSV. Letto nell'ordine in cui il PDF scrive le parole (use_text_flow=True)
  ogni giocatore è una riga pulita:
      ABATE VALERIA LOLA O30 ASSOCIAZIONE … ( NON AFFILIATO PER LA STAGIONE 2023 ) 4.NC 0
  e la si scompone con _RE_RIGA leggendo da destra: [promozione] coefficiente classifica, poi
  categoria d'età (valori fissi, così "BERGAMI EVA" non diventa categoria "EVA"), il resto è
  nome e società. Se la FITP cambia il formato, si tocca SOLO _RE_RIGA / CATEGORIE_ETA.

Maschile o femminile: NON dal titolo (il PDF femminile di luglio 2026 ha nel titolo "- Uomini",
errore della FITP) ma dal testo sotto il titolo: "giocatrici" = femminile, "giocatori" = maschile.
Ogni pagina che contiene il titolo "Promozioni classifiche beach tennis" apre una sezione.

Come si evitano i disastri:
  - controlli PRIMA di toccare il file: tutte e due le classifiche presenti una volta sola, non lo
    stesso PDF due volte, abbastanza giocatori, formato riconosciuto, nessun calo sospetto di righe.
    Se un controllo fallisce: ValueError con messaggio chiaro e il file attuale NON cambia;
  - la versione precedente viene copiata in data/archivio/ e il file nuovo sostituisce il
    vecchio in un colpo solo (os.replace): chi lo sta leggendo vede o il vecchio o il nuovo.

CIRCOLI (data/circolo_regioni.csv): si AGGIUNGONO righe in fondo, non si sostituisce il file.
  province_circoli()          provincia -> regione come scritte nel csv (per la tendina del modulo)
  aggiungi_circoli(xlsx)      append dei circoli compilati nel file "circoli da mappare"
  circoli_non_presenti(nomi)  quelli dell'elenco non ancora nel csv (pagina finale)
  stato_circoli()             cosa mostrare nella scheda Circoli (tennis / beach)

Le liste dei campionati si leggono in processor/campionato.py (dato della singola partita, non di riferimento).
Per aggiungere un altro aggiornamento basta una funzione aggiorna_<nome> che usa _sostituisci_file()
e _registra().
"""
from __future__ import annotations

import contextlib
import csv
import io
import hashlib
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd
import pdfplumber

from core import conf
from core.errori import ErroreUtente
from processor import file_utente as _fu

# Colonne del CSV prodotto: le prime sei sono quelle che leggono players.df_coeff e
# ranking.ass_coeff (NON rinominarle). "Sesso" è nuova e serve solo per i conteggi.
COLONNE_CSV = ["Tesserato", "Cat. Età", "Società", "Class", "Coeff", "Classifica promozione", "Sesso"]

# Categorie d'età che compaiono nei PDF FITP (luglio 2026). NOR / NOF = senza limite d'età M / F.
CATEGORIE_ETA = r"U\d{2}|O\d{2}|NOR|NOF"
_CLASSIFICA = r"[1-4]\.(?:NC|\d)"
# Una riga giocatore:  NOME  CATEGORIA  SOCIETÀ  CLASSIFICA  COEFFICIENTE  [PROMOZIONE]
# (tra società e classifica lo spazio può mancare: "…CESSATA ATTIVITA'4.NC 0")
_RE_RIGA = re.compile(
    rf"^(?P<nome>.+?)\s+(?P<cat>{CATEGORIE_ETA})\s+(?P<soc>.*?)\s*(?P<cl>{_CLASSIFICA})"
    rf"\s+(?P<coeff>\d+(?:[.,]\d+)?)(?:\s+(?P<promo>{_CLASSIFICA}))?\s*$")
_RE_TITOLO = re.compile(r"promozioni classifiche beach", re.IGNORECASE)
_RE_FEMMINILE = re.compile(r"\bgiocatric", re.IGNORECASE)
_RE_MASCHILE = re.compile(r"\bgiocatori\b", re.IGNORECASE)
_INTESTAZIONE = "Cognome e Nome"
# Righe di testo del PDF che non sono giocatori (titolo, spiegazioni, intestazione della tabella).
_RIGHE_NON_GIOCATORI = ("Promozioni classifiche", "In applicazione", "distribuzione armonica",
                        "a) ", "b) ", "c) ", "in rosa", "in verde", _INTESTAZIONE)

SESSI = {"M": "maschile", "F": "femminile"}
MIN_GIOCATORI_PER_SEZIONE = 100   # sotto: non è una classifica completa
MAX_QUOTA_ANOMALE = 0.01          # oltre l'1% di righe non riconosciute: formato cambiato, ci si ferma
MAX_CALO = 0.50                   # il nuovo file non può avere meno della metà dei giocatori del vecchio


def _log(*_a, **_k):
    pass


# =============================================================================
# Lettura dei PDF
# =============================================================================
def _sesso_sezione(testo_pagina: str) -> str | None:
    f, m = bool(_RE_FEMMINILE.search(testo_pagina)), bool(_RE_MASCHILE.search(testo_pagina))
    return "F" if f and not m else "M" if m and not f else None


def leggi_classifiche_beach(pdf: list[Path], log=None, avanzamento=None) -> pd.DataFrame:
    """Legge uno o più PDF (unito o separati) e restituisce la tabella con le colonne di COLONNE_CSV.

    Solleva ErroreUtente (Err 40-44) se il contenuto non è plausibile."""
    log = log or _log
    avanzamento = avanzamento or (lambda *_: None)
    sezioni: list[dict] = []

    with contextlib.ExitStack() as pila:
        documenti = [(p, pila.enter_context(pdfplumber.open(p))) for p in pdf]
        totale = sum(len(d.pages) for _, d in documenti)
        fatte = 0
        avanzamento(0, totale, "Lettura dei PDF")
        for percorso, documento in documenti:
            log(f"Leggo «{percorso.name}» ({len(documento.pages)} pagine)…")
            for numero, pagina in enumerate(documento.pages, start=1):
                testo = pagina.extract_text(use_text_flow=True) or ""
                if _RE_TITOLO.search(testo):                      # inizia una nuova classifica
                    sesso = _sesso_sezione(testo)
                    if sesso is None:
                        raise ErroreUtente(f"Err 41: a pagina {numero} di «{percorso.name}» inizia una classifica, "
                                         f"ma non capisco se è maschile o femminile (mancano «giocatori» / «giocatrici»).")
                    sezioni.append({"sesso": sesso, "file": percorso.name, "da_pagina": numero, "pagine": 0,
                                    "righe": [], "anomale": [], "intestazioni": 0})
                    log(f"Trovata la classifica {SESSI[sesso]} in «{percorso.name}», da pagina {numero}.")
                if not sezioni:
                    raise ErroreUtente(f"Err 40: «{percorso.name}» non sembra una classifica beach FITP: la prima pagina "
                                     f"non ha il titolo «Promozioni classifiche beach tennis».")
                sezione = sezioni[-1]
                sezione["pagine"] += 1
                for riga in testo.splitlines():
                    riga = riga.strip()
                    if not riga:
                        continue
                    if riga.startswith(_RIGHE_NON_GIOCATORI):
                        sezione["intestazioni"] += riga.startswith(_INTESTAZIONE)
                        continue
                    m = _RE_RIGA.match(riga)
                    if m:
                        sezione["righe"].append(m)
                    else:
                        sezione["anomale"].append(f"{percorso.name} p.{numero}: {riga}")
                fatte += 1
                avanzamento(fatte, totale, f"Lettura classifica {SESSI[sezione['sesso']]}")

    # --- controlli sul contenuto ------------------------------------------------
    trovati = [s["sesso"] for s in sezioni]
    for sesso in ("F", "M"):
        if trovati.count(sesso) > 1:
            raise ErroreUtente(f"Err 42: la classifica {SESSI[sesso]} compare {trovati.count(sesso)} volte. "
                             f"Serve UNA classifica femminile e UNA maschile.")
    mancanti = [SESSI[s] for s in ("F", "M") if s not in trovati]
    if mancanti:
        raise ErroreUtente(f"Err 43: manca la classifica {' e '.join(mancanti)}. Il file dei coefficienti è l'UNIONE "
                         f"delle due: carica il PDF unito, oppure i due PDF FITP insieme.")
    for s in sezioni:
        nome = SESSI[s["sesso"]]
        if not s["intestazioni"]:
            raise ErroreUtente(f"Err 40: nella classifica {nome} non trovo l'intestazione «Cognome e Nome … "
                             f"Coefficiente»: il formato del PDF è cambiato?")
        if len(s["righe"]) < MIN_GIOCATORI_PER_SEZIONE:
            raise ErroreUtente(f"Err 43: dalla classifica {nome} ho letto solo {len(s['righe'])} giocatori: "
                             f"non sembra completa.")
        riconosciute = len(s["righe"]) + len(s["anomale"])
        if len(s["anomale"]) > MAX_QUOTA_ANOMALE * riconosciute:
            esempi = "\n".join(s["anomale"][:3])
            raise ErroreUtente(f"Err 44: nella classifica {nome} {len(s['anomale'])} righe su {riconosciute} non hanno "
                             f"il formato atteso: il PDF è cambiato? File attuale NON modificato. Esempi:\n{esempi}")
        log(f"Classifica {nome}: {len(s['righe'])} giocatori da {s['pagine']} pagine.")
        if s["anomale"]:
            log(f"Att. 47: {nome}: {len(s['anomale'])} righe non riconosciute e quindi escluse: "
                + " | ".join(s["anomale"][:3]))

    dati = [{
        "Tesserato": " ".join(m["nome"].upper().split()),
        "Cat. Età": m["cat"],
        "Società": " ".join(m["soc"].split()),
        "Class": m["cl"].upper(),
        "Coeff": m["coeff"].replace(",", "."),
        "Classifica promozione": (m["promo"] or "").upper(),
        "Sesso": s["sesso"],
    } for s in sezioni for m in s["righe"]]
    return pd.DataFrame(dati, columns=COLONNE_CSV)


# =============================================================================
# Scrittura sicura + registro degli aggiornamenti
# =============================================================================
def _leggi_registro() -> dict:
    if conf.REGISTRO_AGGIORNAMENTI.is_file():
        return json.loads(conf.REGISTRO_AGGIORNAMENTI.read_text(encoding="utf-8"))
    return {}


def _registra(chiave: str, voce: dict) -> None:
    registro = _leggi_registro()
    registro[chiave] = voce
    temporaneo = conf.REGISTRO_AGGIORNAMENTI.with_suffix(".tmp")
    temporaneo.write_text(json.dumps(registro, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporaneo, conf.REGISTRO_AGGIORNAMENTI)


def _archivia(destinazione: Path, log) -> str | None:
    """Copia la versione attuale del file in data/archivio/. Restituisce il nome della copia."""
    if not destinazione.is_file():
        return None
    conf.ARCHIVIO_DIR.mkdir(parents=True, exist_ok=True)
    data_vecchio = datetime.fromtimestamp(destinazione.stat().st_mtime)
    archivio = conf.ARCHIVIO_DIR / f"{destinazione.stem}_fino_al_{datetime.now():%Y%m%d_%H%M%S}{destinazione.suffix}"
    shutil.copy2(destinazione, archivio)
    log(f"Versione precedente (del {data_vecchio:%d/%m/%Y}) copiata in data/archivio/{archivio.name}")
    return archivio.name


def _sostituisci_file(destinazione: Path, df: pd.DataFrame, log) -> str | None:
    """Archivia la versione attuale (se c'è) e scrive la nuova in un colpo solo. Restituisce il file archiviato."""
    archiviato = _archivia(destinazione, log)
    temporaneo = destinazione.with_suffix(".tmp")
    df.to_csv(temporaneo, index=False, encoding="utf-8")
    os.replace(temporaneo, destinazione)
    return archiviato


def _impronta(percorso: Path) -> str:
    return hashlib.sha256(Path(percorso).read_bytes()).hexdigest()


# =============================================================================
# Coefficienti beach
# =============================================================================
def aggiorna_coeff_beach(pdf, log=None, avanzamento=None) -> dict:
    """Nuovo data/coeff_beach.csv dal PDF unito (maschile + femminile) o dai due PDF FITP.

    `pdf`: un percorso, oppure una lista di 1 o 2 percorsi. Tutti i controlli vengono fatti
    PRIMA di toccare il file attuale."""
    log = log or _log
    percorsi = [Path(p) for p in (pdf if isinstance(pdf, (list, tuple)) else [pdf])]
    if not 1 <= len(percorsi) <= 2:
        raise ErroreUtente(f"Err 46: {len(percorsi)} file caricati: serve il PDF unito oppure i due PDF FITP.")
    if len(percorsi) == 2 and _impronta(percorsi[0]) == _impronta(percorsi[1]):
        raise ErroreUtente("Err 42: hai caricato due volte lo stesso PDF. Servono la classifica "
                         "maschile E quella femminile.")

    nuovo = leggi_classifiche_beach(percorsi, log, avanzamento)
    uomini, donne = int((nuovo["Sesso"] == "M").sum()), int((nuovo["Sesso"] == "F").sum())

    if conf.DB_COEF_BT.is_file():
        vecchie = len(pd.read_csv(conf.DB_COEF_BT, dtype=str))
        if len(nuovo) < MAX_CALO * vecchie:
            raise ErroreUtente(f"Err 45: il nuovo file avrebbe {len(nuovo)} giocatori contro i {vecchie} "
                             f"di quello attuale: calo troppo forte, probabilmente un PDF è incompleto. "
                             f"File attuale NON modificato.")

    archiviato = _sostituisci_file(conf.DB_COEF_BT, nuovo, log)
    esito = {
        "file": conf.DB_COEF_BT.name,
        "aggiornato_il": datetime.now().isoformat(timespec="seconds"),
        "pdf": [p.name for p in percorsi],
        "righe": len(nuovo),
        "uomini": uomini,
        "donne": donne,
        "archiviato": archiviato,
    }
    _registra("coeff_beach", esito)
    log(f"Salvato data/{conf.DB_COEF_BT.name}: {len(nuovo)} giocatori ({uomini} uomini, {donne} donne).")
    return esito


def stato_coeff_beach() -> dict:
    """Cosa mostrare nella pagina beach sul file dei coefficienti attuale."""
    percorso = conf.DB_COEF_BT
    stato = {"presente": percorso.is_file(), "file": percorso.name}
    if not stato["presente"]:
        return stato
    voce = _leggi_registro().get("coeff_beach", {})
    modificato = datetime.fromtimestamp(percorso.stat().st_mtime)
    if voce:
        aggiornato, fonte = datetime.fromisoformat(voce["aggiornato_il"]), "Aggiornamento dai PDF"
    else:
        aggiornato, fonte = modificato, "Data del file (nessun aggiornamento registrato)"
    righe = voce.get("righe") or len(pd.read_csv(percorso, dtype=str))
    giorni = (datetime.now() - aggiornato).days
    stato.update({
        "aggiornato": aggiornato,
        "fonte": fonte,
        "righe": righe,
        "uomini": voce.get("uomini"),
        "donne": voce.get("donne"),
        "pdf": voce.get("pdf", []),
        "giorni": giorni,
        "da_aggiornare": giorni > conf.MESI_VALIDITA_COEFF_BT * 30,
    })
    return stato


# =============================================================================
# Circoli (data/circolo_regioni.csv)
# =============================================================================
def _chiave_provincia(testo) -> str:
    """'bolzano ' / 'Bolzano/Bozen' -> 'bolzano' ; 'Forlì-Cesena' -> 'forli-cesena' (per il confronto)."""
    return _fu._norm(str(testo).split("/")[0])


def _leggi_circoli() -> pd.DataFrame:
    """Il csv dei circoli così com'è (stessa lettura di players.mappa_clubs). Err 08 se manca."""
    if not conf.DB_CLUBS.is_file():
        raise FileNotFoundError(f"Err 08: DB circoli non trovato: {conf.DB_CLUBS}")
    return pd.read_csv(conf.DB_CLUBS, delimiter=";", dtype=str).fillna("")


def province_circoli() -> dict[str, str]:
    """Provincia -> regione, prese dal csv dei circoli (sono i nomi che il programma sa già usare)."""
    df = _leggi_circoli()
    df = df[df["Provincia"].str.strip() != ""]
    return {p.strip(): r.strip() for p, r in zip(df["Provincia"], df["Regione"])}


def aggiungi_circoli(percorso, log=None) -> dict:
    """Aggiunge in fondo a circolo_regioni.csv i circoli compilati nel file "circoli da mappare".

    Tutti i controlli vengono fatti PRIMA di scrivere: se una provincia non è riconosciuta non si
    aggiunge niente (Err 49)."""
    log = log or _log
    nome_file = Path(percorso).name
    esistenti = _leggi_circoli()
    chiavi = set(esistenti["Circolo"].str.strip().str.upper())      # stessa chiave di mappa_clubs
    province = province_circoli()
    per_chiave = {_chiave_provincia(p): p for p in province}

    df = _fu.leggi_circoli_compilati(percorso)
    compilati = df[df["Provincia"] != ""]
    senza_provincia = len(df) - len(compilati)
    if compilati.empty:
        raise ErroreUtente(f"Err 51: in «{nome_file}» non c'è nessuna provincia compilata: non c'è niente da aggiungere.")

    sconosciute = [f"«{r.Circolo}»: «{r.Provincia}»" for r in compilati.itertuples()
                   if _chiave_provincia(r.Provincia) not in per_chiave]
    if sconosciute:
        raise ErroreUtente(f"Err 49: in «{nome_file}» ci sono province non riconosciute, nessun circolo aggiunto: "
                           + "; ".join(sconosciute[:5]) + (f" e altre {len(sconosciute) - 5}" if len(sconosciute) > 5 else ""))

    nuovi, gia_presenti = [], []
    for r in compilati.itertuples():
        chiave = r.Circolo.upper()
        if chiave in chiavi:
            gia_presenti.append(r.Circolo)
            continue
        chiavi.add(chiave)                                          # (anche i ripetuti nel file)
        provincia = per_chiave[_chiave_provincia(r.Provincia)]
        nuovi.append((r.Circolo, provincia, province[provincia]))
    if gia_presenti:
        log(f"Att. 50: {len(gia_presenti)} circoli già presenti in {conf.DB_CLUBS.name} (o ripetuti nel file), "
            f"non aggiunti di nuovo: {', '.join(gia_presenti)}")

    esito = {"file": conf.DB_CLUBS.name, "aggiunti": nuovi, "gia_presenti": gia_presenti,
             "senza_provincia": senza_provincia, "archiviato": None}
    if not nuovi:
        return esito

    # append: il vecchio contenuto resta byte per byte, le righe nuove vanno in fondo con lo stesso a capo
    vecchio = conf.DB_CLUBS.read_bytes()
    a_capo = "\r\n" if b"\r\n" in vecchio else "\n"
    righe = io.StringIO()
    csv.writer(righe, delimiter=";", lineterminator=a_capo).writerows(nuovi)
    contenuto = vecchio + (b"" if vecchio.endswith(b"\n") else a_capo.encode()) + righe.getvalue().encode("utf-8")

    esito["archiviato"] = _archivia(conf.DB_CLUBS, log)
    temporaneo = conf.DB_CLUBS.with_suffix(".tmp")
    temporaneo.write_bytes(contenuto)
    os.replace(temporaneo, conf.DB_CLUBS)

    # verifica: rilettura come la fa players.mappa_clubs (se non torna è un errore del programma)
    riletto = _leggi_circoli()
    if len(riletto) != len(esistenti) + len(nuovi):
        raise RuntimeError(f"{conf.DB_CLUBS.name}: attese {len(esistenti) + len(nuovi)} righe dopo l'aggiunta, "
                           f"lette {len(riletto)}. La versione precedente è in data/archivio/{esito['archiviato']}.")

    _registra("circoli", {"aggiornato_il": datetime.now().isoformat(timespec="seconds"), "da_file": nome_file,
                          "aggiunti": len(nuovi), "totale": len(riletto), "archiviato": esito["archiviato"]})
    for circolo, provincia, regione in nuovi:
        log(f"Aggiunto: {circolo} · {provincia} · {regione}")
    return esito


def circoli_non_presenti(nomi: list[str]) -> list[str]:
    """I circoli dell'elenco che (ancora) non sono nel csv: dopo un'aggiunta la pagina finale si aggiorna."""
    chiavi = set(_leggi_circoli()["Circolo"].str.strip().str.upper())
    return [n for n in nomi if n.strip().upper() not in chiavi]


def stato_circoli() -> dict:
    """Cosa mostrare nella scheda Circoli: quanti sono e quando è stata fatta l'ultima aggiunta."""
    percorso = conf.DB_CLUBS
    stato = {"presente": percorso.is_file(), "file": percorso.name}
    if not stato["presente"]:
        return stato
    voce = _leggi_registro().get("circoli", {})
    stato.update({
        "circoli": len(_leggi_circoli()),
        "aggiornato": datetime.fromisoformat(voce["aggiornato_il"]) if voce
                      else datetime.fromtimestamp(percorso.stat().st_mtime),
        "ultima_aggiunta": voce.get("aggiunti"),
    })
    return stato

