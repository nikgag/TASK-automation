import re
import pdfplumber
from pathlib import Path
import pandas as pd

from core import conf, normalize, excel_style
from dataclasses import dataclass
from processor import players as ply
from processor import file_utente as _fu

''' 
Da gestire: 
1) dataclass per player
2) creatore del file csv per estrazione dati dal pdf 
3) matcher per confronto tra pdf e infile excel con dati di sgat
4) aggiustare i percorsi dei file

2) ogni file pdf del CS ha intestazioni diverse, tra la seire A e 
serie B cambia parecchio e pure tra girone e play-off/out, la funzione deve 
essere intelligente per capire cosa stiamo trattando,

'''

# --- tipi di campionato ----
TIPO_A = "serie A"
TIPO_A_POFF = "serie A p-off"
TIPO_B = "serie B"
TIPO_ND = "sconosciuto"

# Colonne che ci si aspetta di trovare, per tipo di campionato.
PROFILI: dict[str, dict[str, tuple[str, ...]]] = {
    TIPO_B: {
        "attese": ("cognome", "nome", "rank", "settore_eta", "variato", "vivaio", "nat"),
        "assenti": ("rank_intl", "rank_intl_oltre", "schieramento"),
    },
    TIPO_A: {
        "attese": ("cognome", "nome", "rank", "settore_eta", "variato", "vivaio", "nat"),
        "assenti": ("schieramento",),
    },
    TIPO_A_POFF: {
        "attese": ("cognome", "nome", "rank", "settore_eta", "variato", "vivaio", "nat",
                   "rank_intl", "rank_intl_oltre", "schieramento"),
        "assenti": (),
    },
    TIPO_ND: {"attese": ("cognome", "nome", "rank"), "assenti": ()},
}

_RE_SERIE = re.compile(r"SERIE[ _-]*([AB])[ _-]*([12])?(?!\d)")
_RE_PLAYOFF = re.compile(r"PLAY[ _-]*(OFF|OUT)")
RE_CLASSIFICA = re.compile(r"([1-4]\.(?:\d{1,2}|NC))\b", re.IGNORECASE)


# --- INFO LISTA
VIVAIO = "Si"; VARIATO = {"T", "N", "S"}

COL_BASE = [
    "Match Lista - SGAT - Tess", "N.", "Cognome", "Nome", "Num. Tessera",
    "Classifica (Lista)", "Classifica (SGAT)", "Classifica (Tess)",
    "Variato", "Vivaio", "Nazionalità (Lista)", "Cittadinanza (Tessera)",
    "Certificato medico", "Link tessera",
]

COL_A = ["ATP/WTA 1-500", "ATP/WTA 501>", "Schieramento"]

CASA, OSPITE = (0, 1, 4, 5), (0,)   # nome, palle, superficie, superficie riserva

#data class pdf, giocatori da players
@dataclass
class Lista: 
    #dati squadra
    squadra: str = "" 
    palle: str = ""
    campi: str = ""
    riserva: str = ""

    #giocatori da lista
    n_schieramento: str = ""
    schieramento_poff: str=""
    cognome: str = ""
    nome: str = ""
    rank_ita: str = ""
    rank_int_1_500: str = ""
    rank_int_501: str = ""
    vivaio: str = ""
    variato: str = ""
    nat: str = ""
    cat_eta: str = ""
    dubbia: bool = False
    
    #capiamo il tipo di lista (dal file pdf)
    tipo: str = TIPO_ND
    serie: str = ""
    nome_file: str = ""
    poff: bool = False
    
    @property
    def etichetta(self) -> str:
        pezzi = [f"Serie {self.serie}" if self.serie else self.tipo]
        if self.poff:
            pezzi.append("playoff/playout")
        return " ".join(pezzi)
    
# funzioni generali: 
def _testo(valore) -> str:
    """Cella -> stringa pulita. '' se vuota o NaN."""
    if valore is None:
        return ""
    t = str(valore).strip()
    return "" if t.lower() == "nan" else t

def _log(*_args, **_kwargs):
    pass

#capiamo che tipo di file abbiamo davanti
def tipo_campionato(in_file) -> str:
    """Tipo di campionato dal nome del file: 'serie A', 'serie A p-off', 'serie B'.

    ATTENZIONE: si guarda SOLO il nome del file, mai il percorso. Cercare 'B'
    nel percorso completo classificherebbe come serie B qualsiasi file dentro
    una cartella che contiene una B (tipo '.../File CS/DB/').
    """
    return leggi_info(in_file).tipo

def leggi_info(in_file) -> Lista:
    """Legge tutto quello che il nome del file dice: serie, sesso, anno, versione."""
    # upload di Flask: .name è il nome del campo del form, il nome del file è .filename
    grezzo = str(getattr(in_file, "filename", None) or getattr(in_file, "name", in_file))
    nome = Path(grezzo).name.upper()

    info = Lista(nome_file=Path(grezzo).name)
    info.poff = bool(_RE_PLAYOFF.search(nome))

    m = _RE_SERIE.search(nome)
    if m:
        lettera, numero = m.group(1), m.group(2) or ""
        info.serie = f"{lettera}{numero}"
        if lettera == "B":
            info.tipo = TIPO_B
        else:
            info.tipo = TIPO_A_POFF if info.poff else TIPO_A
    return info

#leggiamo il pdf e cotruiamo il dataSet
def dati_squadra(righe: list[list[str]], i: int, ospite: bool = False) -> list[str]: 
    for offset in (1,2):
        if i - offset < 0 :
            break
        piene = [c.strip() for c in righe[i - offset] if c and c.strip()]
        if len(piene) == 6:
            return [piene[j] for j in (OSPITE if ospite else CASA)]
    return []

def mappa_colonne_lista(colonne: list[str]) -> dict[str, int]:
    
    mappa: dict[str, int] = {}
    
    for j, intest in enumerate(colonne):
        text = _testo(intest).lower()
        if not text: 
            continue
        for campo, alias in conf.CAMPI.items():
            if campo in mappa: 
                continue
            if text in alias or any(text.startswith(a) for a in alias):
                mappa[campo] = j
                break
    # nei PDF FITP la prima colonna (ordine di schieramento) non ha intestazione
    if "numero" not in mappa and colonne and not _testo(colonne[0]):
        mappa["numero"] = 0
    return mappa

def get_ranking(row: list[str], idx: int | None) -> tuple[str, bool]: 
    #tiene conto che alcuni nomi potrebbero sbordare quindi deve pulire la cella per avere la class
    if idx is not None and idx < len(row):
        cella = row[idx]
        m = RE_CLASSIFICA.search(cella)
        if m:
            pulita = normalize.normalizza_classifica(m.group(1))
            return pulita, cella.strip() != m.group(1)
    for cella in row:                              # ripiego: cercala altrove
        m = RE_CLASSIFICA.fullmatch(cella.strip())
        if m:
            return normalize.normalizza_classifica(m.group(1)), True
    return "", False

def leggi_lista(pdf, log=None) -> list[Lista]: 
    info_file = leggi_info(pdf) #tutte info solo dal nome del file
    
    righe: list[list[str]] = []
    out: list[Lista] = []
    mappa: dict[str, int] = {}
    log = log or _log
    squadra = palle = campi = riserva = ""
    
    with pdfplumber.open(pdf) as in_pdf: 
        for pagina in in_pdf.pages:
            for tabella in pagina.extract_tables():
                for row in tabella: 
                    righe.append([_testo(c).replace("\n", " ") for c in row])
    
    for i, row in enumerate(righe): 
        if not any(row): 
            continue
        
        minu = [c.lower() for c in row]
        
        if "cognome" in minu and "nome" in minu: 
            new = mappa_colonne_lista(row)
            
            if new.get("rank") is not None or not mappa:
                mappa = new # ?? 
            
            team = dati_squadra(righe, i)
            if team:
                squadra = team[0]
                if len(team) >= 4:
                    palle, campi, riserva = team[1], team[2], team[3]
                else:
                    palle = campi = riserva = ""
            
        
        idx_cognome = mappa.get("cognome") 
        if idx_cognome is None or idx_cognome >= len(row):
            continue
        cognome = row[idx_cognome] 
        # confronto in minuscolo; salta anche la riga di intestazione "Cognome"
        if not cognome or cognome.lower() in {x.lower() for x in conf.INTESTAZIONI} | {"cognome"}:
            continue #skippo righe di intestazione
        
        #classifica
        rank, dubt = get_ranking(row, mappa.get('rank'))
        if not rank:
            continue #skippo riga se è vuota
        
        
        def campo(nome: str, _row=row, _mappa=mappa) -> str:
            j = _mappa.get(nome)
            return _row[j] if j is not None and j < len(_row) else ""
        
        #controlliamo il tipo di giornata
        schieramento = campo("schieramento") if info_file.poff else ""
            
        #controllo se serie A
        if info_file.serie in ("A1", "A2"):
            rank_int_1_500 = campo("rank_intl")
            rank_int_501 = campo("rank_intl_oltre")
        else:
            rank_int_1_500 = rank_int_501 = ""
        
        out.append(Lista(
            #dati tipo di lista
            tipo=info_file.tipo,
            serie=info_file.serie,
            nome_file=info_file.nome_file,
            poff=info_file.poff,
            
            #dati squadra
            squadra = squadra, 
            palle = palle, 
            campi= campi,
            riserva=riserva, 
            
            #giocatori listati
            n_schieramento = campo('numero'),
            schieramento_poff=schieramento, #da controllare con if perchè non è sempre presente
            cognome=cognome,
            nome=campo('nome'),
            rank_ita=rank,
            rank_int_1_500=rank_int_1_500,
            rank_int_501=rank_int_501,
            
            #status
            vivaio=campo('vivaio'),
            variato = campo('variato'),
            nat = campo('nat'),
            cat_eta=campo("settore_eta"),
            dubbia= dubt,
        ))

    if not out:
        log('Err 11: nessun giocatore estratto dal PDF della lista.')
        return out


    log(f"{info_file.nome_file}: {len(out)} iscritti, "
        f"{len({i.squadra for i in out})} squadre.")
    verifica_campionato(mappa, info_file, log=log)


    dubbie = [i for i in out if i.dubbia]
    if dubbie:
        log(f"Att. 16: {len(dubbie)} righe con testo sbordato tra le colonne "
            f"(es. '{dubbie[0].cognome} {dubbie[0].nome}'): nome e cognome possono "
            f"essere troncati, controllali a mano nel foglio.")

    return out

def verifica_campionato(mappa: dict[str, int], info: Lista, log=None) -> list[str]:
    log=log or _log
    tipo_campionato = PROFILI.get(info.tipo, PROFILI[TIPO_ND])
    mancanti = [c for c in tipo_campionato['attese'] if c not in mappa]
    if mancanti:
          log(f"Att. 17: nel PDF ({info.tipo}) mancano le colonne attese: "
                    f"{', '.join(mancanti)}.")
    inattese = [c for c in tipo_campionato["assenti"] if c in mappa]  
    if inattese:
            log(f"Att. 18: il PDF ha colonne non previste per {info.tipo}: "
                f"{', '.join(inattese)}. Il tipo dedotto dal nome file potrebbe essere sbagliato.")
    return mancanti           

# controlliamo che i campi corrispondono alla Lista: SGAT == LISTA ?
def corrispondenza(player, lista) -> bool: 
    #player è il dataclass che contiene sia tessera che sgat
    #lista solo info delle liste
    corr = False 
    
    def pulisci(x):
        # senza accenti ("Sì" / "SI"); "N/D" (campo non trovato dal driver) = vuoto
        s = normalize.normalizza_nome(str(x).replace(',', '.')).upper()
        return "" if s in ("NAN", "NONE", "N/D") else s
    
    if lista is None:
        flag = "Non in Lista"
        return corr, flag
    
    rank = {
            'rank_sgat': (lista.rank_ita, player.rank),
            'rank_tess': (lista.rank_ita, player.rank_tess),
    }
    
    v_v_n = {
        'nat': (lista.nat, player.nat),
        'viv': (lista.vivaio, player.vivaio),
        'var': (lista.variato, player.variato),
    }
    
    # rank_tess si confronta solo se la tessera ha dato un valore
    diversi = [c for c, (a,b) in rank.items()
               if (c == 'rank_sgat' or pulisci(b)) and pulisci(a) != pulisci(b)]
    diversi += [c for c, (a,b) in v_v_n.items() if pulisci(b) and pulisci(a) != pulisci(b)]
    
    if not diversi: 
        corr = True; flag='SI'
        return corr, flag
    else: 
        flag = f"NO ({', '.join(diversi)})"
        return corr, flag
    
def foglio_cs(ws, lista: list[Lista], sgat_file: str, squadra_casa: str, data: str, driver=None, log=None,
              avanzamento=None):

    testa = lista[0]   # dati di squadra/lista, uguali per tutti i giocatori
    squadra = testa.squadra
    nome_foglio = 'casa' if squadra_casa == squadra else 'ospite'

    df_sgat = _fu.leggi_sgat(sgat_file, log, ruoli=(nome_foglio,))[nome_foglio]
    giocatori = ply.campionato(df_sgat, data, squadra, driver, log, avanzamento)

    # indice (COGNOME, NOME) -> giocatore della lista
    per_nome = {(g.cognome.strip().upper(), g.nome.strip().upper()): g for g in lista}

    # intestazione: colonne extra solo se serie A e/o playoff
    # testa.tipo ("serie A"), non testa.serie ("A2", "B1"…)
    serie_A = testa.tipo in (TIPO_A, TIPO_A_POFF)
    col = COL_BASE + (COL_A if serie_A else []) + (["Schierabile playoff"] if testa.poff else [])

    ws.append(col)
    excel_style.formatta_file(ws, colore_header=conf.COLORE_HEADER)
    link_col = col.index("Link tessera") + 1
    
    for n, p in enumerate(giocatori, start=1):
        g = per_nome.get((p.cognome.strip().upper(), p.nome.strip().upper()))
        corr, flag = corrispondenza(p, g)
        g = g or Lista()   # giocatore non in lista: campi vuoti

        riga = [flag, n, p.cognome, p.nome, p.tessera,
                g.rank_ita, p.rank, p.rank_tess,
                g.variato, g.vivaio, g.nat, p.nat,
                p.med, p.link]
        if serie_A:
            riga += [g.rank_int_1_500, g.rank_int_501, g.n_schieramento]
        if testa.poff:
            riga.append(g.schieramento_poff)

        ws.append(riga)

        cell = ws.cell(row=ws.max_row, column=link_col, value=f"Tessera {p.cognome}")
        cell.hyperlink = p.link
        cell.font = excel_style.FONT_LINK

    excel_style.evidenzia_corrispondenza(ws, nome_colonna=col[0])

    in_sgat = {(p.cognome.strip().upper(), p.nome.strip().upper()) for p in giocatori}
    mancanti = [f"{c} {n}" for (c, n) in per_nome if (c, n) not in in_sgat]
    if mancanti:
        (log or _log)(f"Att. 22: {squadra}: in lista PDF ma non nel file SGAT: {', '.join(mancanti)}")

    nome_foglio_new = f"{nome_foglio} - {squadra}"
    ws.title = re.sub(r'[\\/*?:\[\]]', '', nome_foglio_new)[:31]
