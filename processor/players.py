from __future__ import annotations
 
from collections import defaultdict
from dataclasses import dataclass
 
import pandas as pd
 
from core import conf, excel_style, normalize, ranking
 
 
# =============================================================================
# DATACLASS UNICA
# =============================================================================
## foglio giocatori del file excel output
# input: excel da sgat con i dati dei giocatori
# output: DataFrame con i dati preocessati e tessere verificate dal driver
#valido sia per tennis che beach tennis, da considerare se renderlo valido anche per CS
 
# I campi hanno tutti un default: un Player si puo' costruire in modo completo
# (stadio ingest) oppure minimale (solo i campi utili al seeding), senza bisogno
# di una seconda dataclass. `rank` = la classifica RTS (nome originario di players.py).
# Ultima modifica: 23/09/2026
#
# versione: 1.2.2


@dataclass
class Player:
    sport: str = ""                  # Lo prende da input utente
    tessera: str = ""
    cognome: str = ""
    nome: str = ""
    rank: str = ""
    club: str = ""
    prov: str = ""
    reg: str = ""
    link: str = ""
    med: str | None = None
    nat: str | None = None
    coefficiente: float = 0.0        # Attivo nel beach 
    numero_squadra: str | int | None = None  
    valore_coppia: int | None = None #valore coppia tennis
    
    # Campionato a squadre
    squadra: str | None = None
    vivaio: str | None = None        
    variato: str | None = None
    rank_tess: str | None = None

# Valore RTS di ripiego per una classifica non in tabella (spinge in fondo).
_DEFAULT_VALORE = ranking.VALORE_SCONOSCIUTO       # 100
_DEFAULT_CLASS_NUM = 33                            # come nell'originale beach
 
 
@dataclass
class Coppia:
    squadra: object
    a: Player
    b: Player
    somma_valori: int
    somma_coeff: float | None
 
 
#intestazione dei fogli
 
SGAT = [
    "Num. Tessera", "Cognome", "Nome", "Classifica", "Circolo",
    "Link tessera", "Provincia", "Regione",
]
 
# Colonne del foglio giocatori. Il beach aggiunge "Coefficiente" dopo "Classifica".
COL_NEW = [
    "Num. Tessera", "Cognome", "Nome", "Classifica", "Circolo",
    "Certificato medico", "Cittadinanza", "Link tessera", "Provincia", "Regione",
]
 
COL_NEW_BEACH = [
    "Num. Tessera", "Cognome", "Nome", "Classifica", "Coefficiente", "Circolo",
    "Certificato medico", "Cittadinanza", "Link tessera", "Provincia", "Regione",
]
 
# COSTANTI
UNKOWN_PROV = 'ND non presente in DB'
UNKOWN_REG = 'ND'
 
 
def _log(*_args, **_kwargs):
    pass
 
 
# =============================================================================
# STADIO 1 — INGEST / ARRICCHIMENTO
# =============================================================================
#mappa circolo - regione
# chiave = nome del circolo (maiuscolo); la regione è quella del circolo, non la residenza del giocatore
def mappa_clubs(csv) -> dict[str, tuple[str,str]]:
 
    df = pd.read_csv(csv, delimiter=';')
    mappa: dict[str, tuple[str,str]] = {}
 
    for _, line in df.iterrows():
        circolo = str(line["Circolo"]).strip().upper()
        regione = str(line["Regione"]).strip()
        provincia = str(line["Provincia"]).strip()
 
        if regione == "Trentino-Alto Adige/Südtirol":
            if provincia == "Trento":
                regione = "Trento"
            elif provincia == "Bolzano/Bozen":
                regione = "Bolzano"
        elif regione == "Valle d'Aosta/Vallée d'Aoste":
            regione = "VDA"
        # nel csv queste regioni sono scritte col trattino
        elif regione in ("Friuli Venezia Giulia", "Friuli-Venezia Giulia"):
            regione = "Friuli"
        elif regione in ("Emilia Romagna", "Emilia-Romagna"):
            regione = "Emilia"
 
        mappa[circolo] = (provincia, regione)
    return mappa
 
#controllo su equiparati, toglie le righe
def _rimuovi_equiparati(df: pd.DataFrame, log) -> pd.DataFrame:
    if "Nome" not in df.columns:
        return df
    maschera = df["Nome"].astype(str).str.strip().str.upper() == "EQUIPARATO"
    n = int(maschera.sum())
    if n:
        log(f"Salto {n} riga/e 'Equiparato' (segnaposto, non giocatori reali).")
        df = df[~maschera].reset_index(drop=True)
    return df

def df_coeff(file=conf.DB_COEF_BT):
    # '_key' = nome normalizzato per il confronto in ranking.ass_coeff
    df = pd.read_csv(file, dtype=str)
    df["_key"] = df["Tesserato"].map(lambda t: " ".join(normalize.normalizza_nome(t).split()).upper())
    return df


def player_list(df_ply: pd.DataFrame, mappa_clubs: dict[str, tuple[str,str]], data_inizio: str | None = None, data_fine: str | None = None,
    driver = None,
    log = None,
    sport = None,
    col_coeff: str | None = None,      # colonna coefficiente (beach)
    col_squadra: str | None = None,    # colonna numero squadra (doppio)
    avanzamento = None,                # avanzamento(fatti, totale) per la barra della GUI
    ) -> list[Player]:

    log = log or _log
    df = _rimuovi_equiparati(df_ply, log)
    data: list[Player] = []

    #coeff beach
    tabella_coeff = df_coeff() if sport == 'beach' else None

    avanzamento = avanzamento or (lambda *_: None)
    totale = len(df)
    avanzamento(0, totale)
    circoli_ignoti: set[str] = set()

    for fatti, (_, row) in enumerate(df.iterrows(), start=1):
        circolo_raw = row.get("Circolo")
        circolo = "" if pd.isna(circolo_raw) else str(circolo_raw).strip()
        club_key = circolo.upper()
 
        tessera = normalize.normalizza_tessera(row.get("Num. Tessera"))
        classifica = normalize.normalizza_classifica(row.get("Class."))
        link = normalize.link_tessera(tessera)
 
        if club_key in mappa_clubs:
            prov, reg = mappa_clubs[club_key]
        else:
            prov, reg = UNKOWN_PROV, UNKOWN_REG
            if club_key not in circoli_ignoti:
                circoli_ignoti.add(club_key)
                log(f"Att. 01: circolo «{club_key}» non trovato in {conf.DB_CLUBS.name}: regione ND.")
 
 
        med = nat = None
 
        if driver is not None :
            med, nat = driver.tessera_torneo(link, data_inizio, data_fine, tessera)

            if nat is None:
                nat = 'ND'
                status = '(Citt. non trovata, verifica manuale)'
                #log(f"Err 02: Tessera '{tessera}' non trovata.")
            elif str(nat).upper() != 'ITALIA':
                status = 'STRANIERO'

            else:
                status = None

            log(f"{row.get('Cognome')}: Certificato={med}, "
                            f"Cittadinanza={nat}" + (f" {status}" if status else ""))
        
        #default coeff e n squadra
        coeff = 0.0
        squadra = None
        
        # se sport è beach estraggo i coefficienti
        if sport == 'beach':
            # nel DB coefficienti 'Tesserato' è "COGNOME NOME"
            ply = " ".join((normalize.normalizza_nome(row.get('Cognome')) + " "
                            + normalize.normalizza_nome(row.get('Nome'))).split()).upper()
            # chi non è nel DB tiene la classifica SGAT; "3,2" -> "3.2" per la mappa RTS
            coeff, classifica = ranking.ass_coeff(ply, circolo, tabella_coeff, rank_default=classifica)
            classifica = normalize.normalizza_classifica(classifica)

        #capisco se siamo nel doppio
        if col_squadra is not None:
            squadra = row.get(col_squadra)
            # cella vuota = NaN (sempre diverso da sé stesso): diventa None
            if pd.isna(squadra):
                squadra = None
            
        data.append(Player(
            tessera= tessera,
            cognome = str(row.get('Cognome', '')),
            nome= str(row.get('Nome', '')),
            rank= classifica,
            club=circolo,
            prov=prov,
            reg=reg,
            link=link,
            med=med,
            nat=nat,
            coefficiente=coeff,
            numero_squadra=squadra,
        ))
        avanzamento(fatti, totale)

    return data
 

def campionato(df: pd.DataFrame, data: str | None = None, team: str | None = None, driver = None, log = None,
               avanzamento = None) -> list[Player]:

    log = log or _log
    record: list[Player] = []


    # nel file SGAT la colonna è "class " (minuscolo, spazio finale): intestazioni normalizzate
    df = df.rename(columns=lambda c: str(c).strip().lower())

    avanzamento = avanzamento or (lambda *_: None)
    totale = len(df)
    avanzamento(0, totale)

    for fatti, (_, row) in enumerate(df.iterrows(), start=1):
        n_tessera_SGAT = normalize.normalizza_tessera(row.get("tessera"))
        rank_SGAT = normalize.normalizza_classifica(row.get("class"))
        link = normalize.link_tessera(n_tessera_SGAT)
        
        #controllo tessera 
        
        #med = nat = viv = var = rank_tess = None
        tessera_record = [None, None, None, None, None]
        
        if driver is not None: 
            dati_tess = driver.tessera_cs(link, data, n_tessera_SGAT)
            
            tessera_record = [val if val is not None else "N/D" for val in dati_tess]

            log(f"{str(row.get('cognome', '')).strip()} {str(row.get('nome', '')).strip()}: "
                f"Certificato={tessera_record[0]}, Cittadinanza={tessera_record[1]}, "
                f"Classifica tessera={tessera_record[4]}")


        record.append(Player(
            tessera = n_tessera_SGAT,
            cognome = str(row.get('cognome', '')).strip(),
            nome = str(row.get('nome', '')).strip(),
            rank = rank_SGAT,
            link = link,
            med = tessera_record[0],
            nat = tessera_record[1],
            squadra = team, 
            vivaio = tessera_record[2], 
            variato = tessera_record[3],
            rank_tess = tessera_record[4],
        ))
        avanzamento(fatti, totale)

    log(f'Analizzati {len(record)} giocatori da foglio sgat')
    return record 
        
def foglio_ply(ws, records: list[Player], sport: str = "tennis"):
    
    #check su tipy di gara
    beach = str(sport).lower() == "beach"
    doppio = any(p.numero_squadra is not None for p in records)

    #instestazioni
    col = list(COL_NEW_BEACH) if beach else list(COL_NEW)
    if doppio:
        idx_circolo = col.index("Circolo")
        col.insert(idx_circolo, "Squadra")
        col.insert(idx_circolo + 1, 'Valore Coppia')

    #worksheet
    ws.append(col)
    excel_style.formatta_file(ws, colore_header=conf.COLORE_HEADER)
 
    link_col = col.index("Link tessera") + 1 
 
    for r in records:
        if beach and doppio: #beach doppio
            riga = [r.tessera, r.cognome, r.nome, r.rank, r.coefficiente, r.numero_squadra, r.valore_coppia, r.club,
                    r.med, r.nat, "", r.prov, r.reg]
        elif beach and not doppio: #beach singolo
            riga = [r.tessera, r.cognome, r.nome, r.rank, r.coefficiente, r.club,
                    r.med, r.nat, "", r.prov, r.reg]
        elif doppio: # Tennis doppio
            riga = [r.tessera, r.cognome, r.nome, r.rank, r.numero_squadra, r.valore_coppia, r.club,
                    r.med, r.nat, "", r.prov, r.reg]
        else:        # Tennis singolo
            riga = [r.tessera, r.cognome, r.nome, r.rank, r.club,
                    r.med, r.nat, "", r.prov, r.reg]
            
        ws.append(riga)
        
        cell = ws.cell(row=ws.max_row, column=link_col, value=f"Tessera {r.cognome}")
        cell.hyperlink = r.link
        cell.font = excel_style.FONT_LINK

# ---  beach ---------------------------
#Entry list beach sia singolo che doppio
def entry_beach(ws, ply: list[Player], log=None):
        # capiamo se singolo o doppio
        doppio = any(p.numero_squadra for p in ply)

        if doppio:
            order = ordina_doppio(ply, "beach", log=log)
            scrivi_doppio(ws, order)
        else: 
            order = ordina_singolo(ply)
            scrivi_singolo(ws, order)

def ordina_singolo(giocatori: list[Player], sport: str = "beach") -> list[Player]:
    mappa = ranking.mappa_per_sport(sport)
 
    def chiave(g: Player):
        valore = mappa.get(str(g.rank), _DEFAULT_VALORE)
        class_num = mappa.get(str(g.rank), _DEFAULT_CLASS_NUM)
        return (valore, class_num, -ranking.safe_float(g.coefficiente))
 
    return sorted(giocatori, key=chiave)
 
def forma_coppie(giocatori: list[Player], sport: str = "tennis", log=None) -> list[Coppia]:
    """Raggruppa i giocatori per numero squadra e calcola forza/coeff della coppia."""
    log = log or _log
    mappa = ranking.mappa_per_sport(sport)
    squadre: dict[object, list[Player]] = defaultdict(list)
    for g in giocatori:
        if g.numero_squadra is None:
            log(f"Att. 19: {g.cognome} {g.nome} senza numero squadra: escluso dal doppio.")
            continue
        squadre[g.numero_squadra].append(g)

    coppie: list[Coppia] = []
    for squadra, membri in squadre.items():
        if len(membri) < 2:
            # coppia incompleta: la segnaliamo saltandola (chi orchestra puo' loggare)
            log(f"Att. 20: squadra {squadra} incompleta ({membri[0].cognome}): esclusa dal doppio.")
            continue
        if len(membri) > 2:
            log(f"Att. 21: squadra {squadra} ha {len(membri)} giocatori: uso solo i primi 2.")
        ordinati = sorted(membri, key=lambda x: str(x.rank))
        a, b = ordinati[0], ordinati[1]
        somma_valori = (mappa.get(str(a.rank), _DEFAULT_VALORE)
                        + mappa.get(str(b.rank), _DEFAULT_VALORE))
        
        if str(sport).lower() == 'beach': 
            somma_coeff = ranking.safe_float(a.coefficiente) + ranking.safe_float(b.coefficiente)
        else: 
            somma_coeff = None
        coppie.append(Coppia(squadra, a, b, somma_valori, somma_coeff))
    return coppie
 
def ordina_doppio(giocatori: list[Player], sport: str = "tennis", log=None) -> list[Coppia]:
    """Ordina le coppie per il tabellone doppio (somma valori RTS crescente)."""
    mappa = ranking.mappa_per_sport(sport)
    coppie = forma_coppie(giocatori, sport, log=log)
 
    def chiave(c: Coppia):
        va = mappa.get(str(c.a.rank), _DEFAULT_VALORE)
        vb = mappa.get(str(c.b.rank), _DEFAULT_VALORE)
        # nel tennis somma_coeff è None: vale 0
        return (c.somma_valori, va, vb, -(c.somma_coeff or 0.0))
 
    return sorted(coppie, key=chiave)
 
 
# --- SCRITTURA SU ENTRY LIST BEACH --------------------------------------------------
def scrivi_singolo(ws, giocatori_ordinati: list[Player], riga_start: int = 6) -> None:
    """Scrive entry singolo a partire da `riga_start` (B..E)."""
    r = riga_start
    for g in giocatori_ordinati:
        ws.cell(row=r, column=2, value=g.cognome)
        ws.cell(row=r, column=3, value=g.nome)
        ws.cell(row=r, column=4, value=g.rank)
        ws.cell(row=r, column=5, value=g.coefficiente)
        r += 1
 
def scrivi_doppio(ws, coppie_ordinate: list[Coppia], riga_start: int = 6) -> None:
    """Scrive il tabellone doppio a partire da `riga_start`.
 
    Colonne: B/C/D/E = giocatore A (cognome, nome, classifica, coeff),
             F/G/H/I = giocatore B, J = somma valori, K = formula somma coeff.
    """
    r = riga_start
    for c in coppie_ordinate:
        ws.cell(row=r, column=2, value=c.a.cognome)
        ws.cell(row=r, column=3, value=c.a.nome)
        ws.cell(row=r, column=4, value=c.a.rank)
        ws.cell(row=r, column=5, value=c.a.coefficiente)
        ws.cell(row=r, column=6, value=c.b.cognome)
        ws.cell(row=r, column=7, value=c.b.nome)
        ws.cell(row=r, column=8, value=c.b.rank)
        ws.cell(row=r, column=9, value=c.b.coefficiente)
        ws.cell(row=r, column=10, value=c.somma_valori)
        ws.cell(row=r, column=11, value=f"=E{r}+I{r}")
        r += 1
 


