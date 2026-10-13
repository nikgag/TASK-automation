import re
import unicodedata
import pdfplumber
from pathlib import Path
import csv
from datetime import datetime
from openpyxl.styles import PatternFill


from core import conf, normalize, excel_style
from dataclasses import dataclass, asdict
from processor import players as ply
from processor import file_utente as _fu


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

def _chiave_intest(s) -> str:
    t = re.sub(r"\s+", " ", _testo(s).lower()).strip()
    t = re.sub(r"\s+>", ">", t)
    t = re.sub(r"[\u2010\u2011\u2012\u2013\u2014\u2015]", "-", t)   # trattini Unicode → ASCII
    return re.sub(r"^rank ", "", t)

def _chiave_nome(s) -> str:
    t = unicodedata.normalize("NFKD", _testo(s))
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = re.sub(r"[\'\u2019`\u00b4]", "", t)
    return re.sub(r"\s+", " ", t).strip().upper()

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
        #Comm. Claude: nei PDF A1 la riga squadra ha una cella in piu' ("Ordine di schieramento"):
        #7 celle piene invece di 6, quindi il vecchio controllo non scattava mai. La escludo.
        piene = [c.strip() for c in righe[i - offset]
                 if c and c.strip() and c.strip().lower() not in
                    {"ordine di schieramento", "schieramento"}]
        if len(piene) == 6:
            return [piene[j] for j in (OSPITE if ospite else CASA)]
    return []

def mappa_colonne_lista(colonne: list[str]) -> dict[str, int]:
    
    mappa: dict[str, int] = {}
    
    for j, intest in enumerate(colonne):
        text = _chiave_intest(intest)
        if not text: 
            continue
        for campo, alias in conf.CAMPI.items():
            if campo in mappa: 
                continue
            alias_k = tuple(_chiave_intest(a) for a in alias)
            if text in alias_k or any(text.startswith(a) for a in alias_k):
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
    # se è un CSV, ricostruisco la lista direttamente senza aprire pdfplumber 
    p = Path(str(getattr(pdf, "filename", None) or pdf))
    if p.suffix.lower() == ".csv":
        with open(p, encoding='utf-8', newline="") as f:
            reader = csv.DictReader(f)
            return [Lista(**{
                k: (row[k] == 'True' if k in ('poff', 'dubbia') else row[k])
                for k in Lista.__dataclass_fields__ if k in row
            }) for row in reader]
    # return esco dalla funzione

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
            #Comm. Claude: prima, se la riga squadra non si trovava, restava la squadra
            #PRECEDENTE senza errori. Ora si ferma subito.
            if not team:
                raise ValueError(f"{info_file.nome_file}: riga squadra non trovata sopra "
                                 f"l'intestazione giocatori (riga {i}): {righe[max(i-2,0):i]}")
            squadra = team[0]
            palle, campi, riserva = team[1], team[2], team[3]
            
        
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

# controlliamo che i campi corrispondono alla Lista: SGAT == LISTA 
def corrispondenza(player, lista) -> tuple:
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

    #Comm. Claude:  un blocco per campo, ognuno con la sua regola (prima tutti i campi avevano la stessa condizione)
    diversi = []

    #Comm. Claude:  rank_sgat: fonte meno importante, si confronta solo se la lista ha il valore
    r_sgat = pulisci(player.rank)
    r_lista = pulisci(lista.rank_ita)
    if r_lista and r_lista != r_sgat:
        diversi.append("rank_sgat")

    #Comm. Claude:  rank_tess: deve coincidere con la lista; manca da una parte sola = NO
    r_tess = pulisci(player.rank_tess)
    if r_lista != r_tess:
        diversi.append("rank_tess" if r_lista and r_tess
                       else f"rank_tess: manca in {'lista' if not r_lista else 'tessera'}")

    #Comm. Claude:  nat: campo sempre presente, deve coincidere tra lista e tessera
    nat_l, nat_t = pulisci(lista.nat), pulisci(player.nat)
    if nat_l != nat_t:
        diversi.append("nat" if nat_l and nat_t
                       else f"nat: manca in {'lista' if not nat_l else 'tessera'}")

    #Comm. Claude:  viv: la tessera dà sempre Sì o No; la lista ha Sì se è vivaio e vuoto se non lo è (vuoto + No = OK)
    viv_l, viv_t = pulisci(lista.vivaio), pulisci(player.vivaio)
    if viv_t not in ("SI", "NO"):
        diversi.append(f"viv: tessera non leggibile ({player.vivaio})")
    elif viv_l not in ("", "SI"):
        diversi.append(f"viv: valore strano in lista ({lista.vivaio})")
    elif viv_t == "SI" and viv_l != "SI":
        diversi.append("viv: in tessera ma non in lista")
    elif viv_t == "NO" and viv_l == "SI":
        diversi.append("viv: in lista ma non in tessera")

    #Comm. Claude:  var: la tessera dà N, S, T oppure "-" (non variato); la lista è vuota se non variato. La lettera deve coincidere
    def lettera(x):
        s = pulisci(x)
        return "" if s == "-" else s      # "-" e vuoto = non variato
    var_l, var_t = lettera(lista.variato), lettera(player.variato)
    if var_l != var_t:
        if var_t and not var_l:
            diversi.append(f"var: tessera {var_t}, lista vuota")
        elif var_l and not var_t:
            diversi.append(f"var: lista {var_l}, tessera senza")
        else:
            diversi.append(f"var: lista {var_l} ≠ tessera {var_t}")

    if not diversi:
        corr = True; flag = 'SI'
        return corr, flag
    else:
        flag = f"NO ({', '.join(diversi)})"
        return corr, flag

def trova_in_lista(p, lista: list[Lista]):
    c, n = _chiave_nome(p.cognome), _chiave_nome(p.nome)
    for g in lista:
        if (_chiave_nome(g.cognome), _chiave_nome(g.nome)) == (c, n):
            return g
    #Comm. Claude: stringa completa senza spazi, uguale o prefisso (testo sbordato tra le
    #colonne: "LOKOLI LA"+"URENT ..." vs "LOKOLI"+"LAURENT ...", oppure cognomi doppi)
    tot = (c + n).replace(" ", "")
    cand = [g for g in lista if len(tot) >= 6 and
            (lambda t: t.startswith(tot) or tot.startswith(t))(
                (_chiave_nome(g.cognome) + _chiave_nome(g.nome)).replace(" ", ""))]
    if len(cand) == 1:
        return cand[0]
    cand = [g for g in lista
            if _chiave_nome(g.cognome) == c and n and _chiave_nome(g.nome)
            and (_chiave_nome(g.nome).startswith(n) or n.startswith(_chiave_nome(g.nome)))]
    return cand[0] if len(cand) == 1 else None

def lista_csv(lista: list[Lista], data_upload: str) -> Path:
    """Salva la lista PDF in un CSV persistente in data/campionati/.

    Ritorna il Path del file creato.
    """
    if not lista:
        raise ValueError("lista vuota: nessun giocatore da salvare")

    testa = lista[0]
    sex = 'M' if 'maschile' in testa.nome_file.lower() else 'F'
    nome_csv = f"Lista_{testa.serie}_{sex}_{data_upload}.csv"

    # salva in data/campionati/ (persistente tra i riavvii)
    cartella = conf.DB_DIR / "campionati"
    cartella.mkdir(parents=True, exist_ok=True)
    percorso = cartella / nome_csv

    intestazioni = list(Lista.__dataclass_fields__.keys())
    with open(percorso, mode='w', encoding='utf-8', newline="") as file:
        writer = csv.DictWriter(file, fieldnames=intestazioni, extrasaction='ignore')
        writer.writeheader()
        for g in lista:
            writer.writerow(asdict(g))

    return percorso

# regole campionato
def regole(lista: list[Lista]) -> list[int]:
    testa = lista[0]; sex = 'M' if 'maschile' in testa.nome_file.lower() else 'F'
    #regole CS
    #variati, vivai, stranieri
    if sex == 'M': 
        return [2 , 2, 1]
    else:
        return [1 ,1,1]
        
#scriviamo i fogli:
def foglio_cs(ws, lista: list[Lista], sgat_file: str, squadra_casa: str, data: str, driver=None, log=None,
              avanzamento=None) -> list[ply.Player]:
    """Compila il foglio squadra ('Casa' o 'Ospite') nel modello mod_cs.xlsx.
    
    Scrive sia le colonne visibili (A:M) sia le colonne sorgente (N:V) per le formule,
    e restituisce la lista dei giocatori elaborati.
    """
    testa = lista[0]
    squadra = testa.squadra
    ruolo = 'casa' if squadra_casa == squadra else 'ospite'

    # Intestazione testata foglio squadra
    ws["A1"] = f"{'CASA' if ruolo == 'casa' else 'OSPITE'} · {squadra}"
    ws["A2"] = f"Generato il {datetime.now().strftime('%d/%m/%Y %H:%M')} · fonti: lista campionato (PDF), SGAT, tessere FITP"

    # Lettura SGAT e scraping tessere
    df_sgat = _fu.leggi_sgat(sgat_file, log, ruoli=(ruolo,))[ruolo]
    giocatori = ply.campionato(df_sgat, data, squadra, driver, log, avanzamento)

    # Reset preventivo delle righe dati da 9 a 50 (colonne A..V)
    for r in range(9, 51):
        for c in range(1, 23):
            cell = ws.cell(row=r, column=c)
            cell.value = None
            cell.hyperlink = None

    trovati: set[int] = set()
    riga_idx = 9

    for n, p in enumerate(giocatori, start=1):
        g = trova_in_lista(p, lista)
        if g is not None:
            trovati.add(id(g))
        corr, flag = corrispondenza(p, g)
        g = g or Lista()

        # Determina l'esito per la colonna A (coerente con le formule di mod_cs.xlsx)
        if corr:
            esito_cella = "✔ OK"
        elif p.rank_tess == "NON LETTO" or p.med is None:
            esito_cella = "⚠ VERIFICA"
        else:
            esito_cella = "✖ NO"

        # Colonne A:M (visibili)
        ws.cell(row=riga_idx, column=1, value=esito_cella)
        ws.cell(row=riga_idx, column=2, value=n)
        ws.cell(row=riga_idx, column=3, value=f"{p.cognome} {p.nome}".strip())
        ws.cell(row=riga_idx, column=4, value=p.tessera)
        ws.cell(row=riga_idx, column=5, value=p.rank_tess or g.rank_ita or p.rank or "—")
        ws.cell(row=riga_idx, column=6, value=p.variato if p.variato in ("T", "N", "S") else (g.variato if g.variato in ("T", "N", "S") else "—"))
        ws.cell(row=riga_idx, column=7, value="Sì" if (p.vivaio == "SI" or g.vivaio == "SI") else "No")
        ws.cell(row=riga_idx, column=8, value=p.nat or g.nat or "—")
        ws.cell(row=riga_idx, column=9, value=p.med or "Valido")
        ws.cell(row=riga_idx, column=10, value=g.rank_int_1_500 or g.rank_int_501 or "—")
        ws.cell(row=riga_idx, column=11, value=g.n_schieramento or g.schieramento_poff or "—")
        ws.cell(row=riga_idx, column=12, value=flag if not corr else None)

        cell_link = ws.cell(row=riga_idx, column=13, value=f"Tessera {p.cognome}")
        if p.link:
            cell_link.hyperlink = p.link
            cell_link.font = excel_style.FONT_LINK

        # Colonne N:V (dettaglio fonti a scomparsa per formule)
        ws.cell(row=riga_idx, column=14, value=g.rank_ita or "—")
        ws.cell(row=riga_idx, column=15, value=p.rank or "—")
        ws.cell(row=riga_idx, column=16, value=p.rank_tess or "—")
        ws.cell(row=riga_idx, column=17, value=g.variato if g.variato in ("T", "N", "S") else "—")
        ws.cell(row=riga_idx, column=18, value=p.variato if p.variato in ("T", "N", "S") else "—")
        ws.cell(row=riga_idx, column=19, value="Sì" if g.vivaio == "SI" else "—")
        ws.cell(row=riga_idx, column=20, value="Sì" if p.vivaio == "SI" else ("No" if p.vivaio == "NO" else "NON LETTO"))
        ws.cell(row=riga_idx, column=21, value=g.nat or "—")
        ws.cell(row=riga_idx, column=22, value=p.nat or "—")

        riga_idx += 1

    mancanti = [f"{g.cognome} {g.nome}" for g in lista if id(g) not in trovati]
    if mancanti:
        (log or _log)(f"Att. 22: {squadra}: in lista PDF ma non nel file SGAT: {', '.join(mancanti)}")

    return giocatori

def foglio_stampa(ws, lista_casa: list[Lista], giocatori_casa: list[ply.Player],
                  lista_ospite: list[Lista], giocatori_ospite: list[ply.Player]) -> None:
    """Compila il foglio 'foglio CS' (foglio stampa/mappa di giornata) applicando
    i colori pastello per vivai, variati e stranieri.
    """
    fill_vivaio = PatternFill(start_color=conf.COLORE_PASTELLO_VIVAIO, end_color=conf.COLORE_PASTELLO_VIVAIO, fill_type="solid")
    fill_variato = PatternFill(start_color=conf.COLORE_PASTELLO_VARIATO, end_color=conf.COLORE_PASTELLO_VARIATO, fill_type="solid")
    fill_straniero = PatternFill(start_color=conf.COLORE_PASTELLO_STRANIERO, end_color=conf.COLORE_PASTELLO_STRANIERO, fill_type="solid")

    def _scrivi_blocco(r_start: int, lista_pdf: list[Lista], giocatori: list[ply.Player]):
        # Pulisce le righe prima di scrivere (da C a N)
        for r in range(r_start, r_start + 15):
            for c in range(3, 15):
                cell = ws.cell(row=r, column=c)
                cell.value = None
                cell.fill = PatternFill(fill_type=None)

        # Scrittura giocatori
        r = r_start
        for p in giocatori:
            g = trova_in_lista(p, lista_pdf) or Lista()

            # Rilevamento figure/status per colorazione
            is_viv = (p.vivaio == "SI") or (g.vivaio == "SI")
            is_var = (p.variato in ("T", "N", "S")) or (g.variato in ("T", "N", "S"))
            nat = (p.nat or g.nat or "").strip().upper()
            is_stran = nat not in ("", "ITALIA", "ITA", "ITALIANA", "—", "-")

            colori = []
            if is_viv:
                colori.append(fill_vivaio)
            if is_var:
                colori.append(fill_variato)
            if is_stran:
                colori.append(fill_straniero)

            # Scrittura valori nelle colonne C..N
            ws.cell(row=r, column=3, value=g.n_schieramento or (r - r_start + 1))  # N. schieramento
            c_cognome = ws.cell(row=r, column=4, value=p.cognome)                 # Cognome
            c_nome = ws.cell(row=r, column=5, value=p.nome)                       # Nome
            ws.cell(row=r, column=6, value=p.tessera)                             # Num. Tessera
            ws.cell(row=r, column=7, value=p.rank_tess or g.rank_ita or p.rank)   # Classifica
            ws.cell(row=r, column=8, value=p.variato or g.variato or "—")         # Variato
            ws.cell(row=r, column=9, value="Sì" if is_viv else "—")               # Vivaio
            ws.cell(row=r, column=10, value=p.nat or g.nat or "—")                # Nazionalità
            ws.cell(row=r, column=11, value=g.rank_int_1_500 or "—")              # INT 1-500
            ws.cell(row=r, column=12, value=g.rank_int_501 or "—")                # INT 501>
            ws.cell(row=r, column=13, value="—")                                  # Data Nascita (non da login)
            ws.cell(row=r, column=14, value=p.med or "Valido")                    # Visita Medica

            # Applicazione colori pastello
            if len(colori) >= 2:
                c_cognome.fill = colori[0]
                c_nome.fill = colori[1]
            elif len(colori) == 1:
                c_cognome.fill = colori[0]
                c_nome.fill = colori[0]

            r += 1

    # 1. Intestazione squadra Casa e struttura
    if lista_casa:
        ws.cell(row=1, column=3, value=lista_casa[0].squadra)
        ws.cell(row=3, column=4, value=lista_casa[0].palle)
        ws.cell(row=3, column=5, value=lista_casa[0].campi)
        ws.cell(row=3, column=6, value=lista_casa[0].riserva or "—")
        _scrivi_blocco(5, lista_casa, giocatori_casa)

    # 2. Intestazione squadra Ospite
    if lista_ospite:
        ws.cell(row=22, column=3, value=lista_ospite[0].squadra)
        _scrivi_blocco(24, lista_ospite, giocatori_ospite)

def compila_riepilogo(ws, casa: str, ospite: str, limiti: list[int]) -> None:
    """Compila il foglio 'Riepilogo' inserendo i dettagli dell'incontro e i limiti RTS."""
    ws["A2"] = f"{casa} - {ospite}"
    ws["B2"] = datetime.now().strftime("elaborazione del %d/%m/%Y alle %H:%M")
    ws["B5"] = f"Casa · {casa}"
    ws["C5"] = f"Ospite · {ospite}"
    # Limite variati per Casa e Ospite (riga 13)
    ws["B13"] = limiti[0]
    ws["C13"] = limiti[0]