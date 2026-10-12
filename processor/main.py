"""
Questo script funge da orchestratore principale per la generazione dei tabelloni.
Prende in input le configurazioni del torneo (TypeTorneo) e il file grezzo degli iscritti,
creando un file Excel finale e formattato. Gestisce dinamicamente la creazione dei fogli
(Giocatori, Contatti, Live Score, Programmazione) e applica la logica specifica
per il Beach Tennis (Singolo o Doppio), ricercando automaticamente la colonna squadra 
e compilando il template corretto.

Ultima modifica: 18/09/2026 
Versione: 1.1.0 (Integrazione modulo Beach Tennis)
"""


import sys
import openpyxl
import pandas as pd
from dataclasses import dataclass, field
from pathlib import Path

# cartella del progetto nel path: funziona con `python processor/main.py`, `-m processor.main` e da Flask
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# importiamo i dati per i vari fogli
from core import conf, excel_sheets
from processor import players as _pl
from processor import live_score as _ls
from processor import contatti as _contatti
from processor import campionato as _cs
from processor import file_utente as _fu


__version__ = "1.1.0"
## COSTANTI

PLAYERS_SHEET = "Giocatori"
CONTATTI_SHEET = "Contatti"

DOPPIO_BEACH_NAME = "ENTRY LIST_BT DOPPIO"
SINGOLO_BEACH_NAME= "ENTRY LIST_BT SINGOLARE"

#data class per il foglio
@dataclass
class TypeTorneo: 
    # oggetti obbligari
    file_iscritti: str
    file_output: str
    csv_circoli: str = str(conf.DB_CLUBS)
    sport: str = "tennis"                 # scolta utente 'tennis' | 'beach'
    
    #disciplina 
    doppio: bool = False #scelta utente
    cs: bool = False #scelta utente 
    
    #campionato
    squadra_casa: str = "" #input
    squadra_ospite: str = ""
    lista_pdf: list = field(default_factory=list)
    
    #verifica driver
    data_inizio: str | None = None
    data_fine: str | None = None
    
    #fogli del file output
    gen_contatti: bool = True
    gen_regioni: bool = True
    gen_ls: bool = False #scelta utente
    gen_prog: bool = False #scelta utente
    
    #foglio contatti
    con_quota: bool = True
    quota_under: float = 0.0
    quota_over: float = 0.0
    nome_torneo: str = ""
    
    # programmazione
    modello_prog: str = str(conf.PROGRAMMAZIONE)
    fogli_prog: list[str] = field(default_factory=lambda: ["Programmazione", "OP"]) #non lo ci devo pensare
    
    # lise score
    ls_path: str | None = None
    ls_event: str | None = None
    
# avanzamento(fatti, totale, fase) facoltativo: barra della GUI; da terminale resta None
def _fase(avanzamento, nome):
    if avanzamento is None:
        return None
    return lambda fatti, totale: avanzamento(fatti, totale, nome)


def torneo(opz: TypeTorneo, driver=None, log=None, avanzamento=None) -> dict:

    log = log or (lambda *a: None)
    esito: dict = {"file_output": opz.file_output, "fogli": []}
    
    #configurazione sport
    #config = conf.configura_pipeline(opz.sport)

    # 1) INPUT
    log(f"Leggo iscritti: {opz.file_iscritti}")
    wb = openpyxl.Workbook()
    
    if opz.cs:
        if not Path(conf.MODELLO_CS).is_file():
            raise FileNotFoundError(f"Err 09: modello CS non trovato: {conf.MODELLO_CS}")
        wb = openpyxl.load_workbook(conf.MODELLO_CS)

        ws_casa = wb['Casa']
        ws_ospite = wb['Ospite']
        ws_stampa = wb['foglio CS']
        ws_riepilogo = wb['Riepilogo']

        lista_casa = [g for g in opz.lista_pdf if g.squadra == opz.squadra_casa]
        lista_ospite = [g for g in opz.lista_pdf if g.squadra == opz.squadra_ospite]

        if not lista_casa:
            raise ValueError(f"Err 07: squadra di casa '{opz.squadra_casa}' non trovata nel PDF.")
        if not lista_ospite:
            raise ValueError(f"Err 07: squadra ospite '{opz.squadra_ospite}' non trovata nel PDF.")

        # 1. Compilazione foglio Casa
        giocatori_casa = _cs.foglio_cs(ws_casa, lista_casa, opz.file_iscritti, opz.squadra_casa, opz.data_inizio, driver, log,
                                       _fase(avanzamento, f"Casa - {opz.squadra_casa}"))
        esito['casa_cs'] = f"Trovati {len(lista_casa)} giocatori"

        # 2. Compilazione foglio Ospite
        giocatori_ospite = _cs.foglio_cs(ws_ospite, lista_ospite, opz.file_iscritti, opz.squadra_casa, opz.data_inizio, driver, log,
                                         _fase(avanzamento, f"Ospite - {opz.squadra_ospite}"))
        esito['ospite_cs'] = f"Trovati {len(lista_ospite)} giocatori"

        # 3. Compilazione foglio Stampa ('foglio CS')
        _cs.foglio_stampa(ws_stampa, lista_casa, giocatori_casa, lista_ospite, giocatori_ospite)

        # 4. Compilazione foglio Riepilogo
        limiti = _cs.regole(lista_casa)
        _cs.compila_riepilogo(ws_riepilogo, opz.squadra_casa, opz.squadra_ospite, limiti)

        # 5. Salvataggio del file
        wb.save(opz.file_output)
        esito["fogli"] = wb.sheetnames

        # 6. Info Struttura loggata alla fine in modo evidente
        struttura_msg = f"Info Struttura: Palle: {lista_casa[0].palle}, Campi: {lista_casa[0].campi}"
        if lista_casa[0].tipo in (_cs.TIPO_A, _cs.TIPO_A_POFF) and lista_casa[0].riserva:
            struttura_msg += f", Riserva: {lista_casa[0].riserva}"
        log(f"\033[1m{struttura_msg}\033[0m")
        log(f"Salvato: {opz.file_output}")
    else:

        df_in = _fu.leggi_iscritti(opz.file_iscritti, doppio=opz.doppio, log=log)

        if not Path(opz.csv_circoli).is_file():
            raise FileNotFoundError(f"Err 08: DB circoli non trovato: {opz.csv_circoli}")
        circoli = _pl.mappa_clubs(opz.csv_circoli)

        if opz.sport == "beach" and not Path(conf.ENTRY_BT).is_file():
            raise FileNotFoundError(f"Err 09: modello Entry List non trovato: {conf.ENTRY_BT}")
        
        colonna_team = "Numero Squadra" if opz.doppio else None
        
        ply = _pl.player_list(df_in, circoli, opz.data_inizio, opz.data_fine, driver, log, opz.sport, col_squadra=colonna_team,
                              avanzamento=_fase(avanzamento, "Controllo tessere"))
        
        esito['giocatori'] = len(ply)
        esito['circoli_mancanti'] = sorted({p.club.strip() for p in ply
                                            if p.club and p.club.strip().upper() not in circoli})
        if esito['circoli_mancanti']:
            log(f"{len(esito['circoli_mancanti'])} circoli non trovati in {Path(opz.csv_circoli).name}: "
                f"a fine elaborazione puoi scaricarli, scegliere la provincia e aggiungerli al file.")
        
        ws_ply = wb.active
        ws_ply.title = PLAYERS_SHEET
        
        # 1) Foglio giocatori 
        
        if opz.doppio: 
            coppie_valide = _pl.forma_coppie(ply, sport=opz.sport, log=log)
            
            for coppia in coppie_valide:
                coppia.a.valore_coppia = coppia.somma_valori 
                coppia.b.valore_coppia = coppia.somma_valori
                
            #scrivo foglio giocatori per il doppio
            _pl.foglio_ply(ws_ply, ply, sport=opz.sport)
        else: 
            _pl.foglio_ply(ws_ply, ply, sport=opz.sport)
        
        esito['fogli'].append(PLAYERS_SHEET)
        
        # 2) Contatti
        
        if opz.gen_contatti:
            df_c = df_in[
                df_in.get("Nome", pd.Series(dtype=str)).astype(str).str.upper() != "EQUIPARATO"
            ].reset_index(drop=True)
            ws_c = wb.create_sheet(CONTATTI_SHEET)
            messaggio = f"Buongiorno, sono il GA del Torneo: {opz.nome_torneo}" if opz.nome_torneo else ""
            _contatti.scrivi_foglio_contatti(
                ws_c, df_c, con_quota=opz.con_quota,
                quota_under=opz.quota_under, quota_over=opz.quota_over,
                messaggio=messaggio, log=log,
            )
            esito["fogli"].append(CONTATTI_SHEET)
        
        wb.save(opz.file_output)
        log(f"Salvato: {opz.file_output}")
        
        # 5) PROGRAMMAZIONE (copiata da modello)
        if opz.gen_prog:
            if Path(opz.modello_prog).is_file():
                non_trovati = excel_sheets.copia_fogli(
                    opz.modello_prog, opz.file_output, opz.fogli_prog
                )
                if non_trovati:
                    log(f"Fogli programmazione non trovati nel modello: {non_trovati}")
                esito["fogli"].extend(f for f in opz.fogli_prog if f not in non_trovati)
            else:
                log(f"Modello programmazione non trovato: {opz.modello_prog}")

        # 6) LIVE SCORE (CSV separato)
        if opz.gen_ls:
            evento = opz.ls_event or _ls.deduci_evento(opz.file_iscritti)
            if evento is None:
                log("Err 05: non riesco a capire se il file iscritti è F o M (evento non dedotto).")
            else:
                df_l = df_in[
                    df_in.get("Nome", pd.Series(dtype=str)).astype(str).str.upper() != "EQUIPARATO"
                ].reset_index(drop=True)
                percorso = opz.ls_path or str(
                    Path(opz.file_output).with_name("Live Score.csv")
                )
                n = _ls.scrivi_csv_live_score(df_l, percorso, evento)
                esito["live_score"] = {"file": percorso, "righe": n, "evento": evento}
                log(f"Live Score creato ({n} righe, evento {evento}): {percorso}")
                
        # Beach tennis 
        if opz.sport == "beach":
            # Scegliamo il foglio
            sheet_name = DOPPIO_BEACH_NAME if opz.doppio else SINGOLO_BEACH_NAME

            # Copiamo il foglio fisicamente sul disco
            excel_sheets.copia_foglio(conf.ENTRY_BT, opz.file_output, foglio_sorgente=sheet_name, nuovo_nome="Entry List", zoom=70)

            # Ricarichiamo il file per "vedere" la nuova Entry List
            wb = openpyxl.load_workbook(opz.file_output)
            ws_entry = wb['Entry List']

            # niente log: gli avvisi sulle coppie li ha già dati forma_coppie
            _pl.entry_beach(ws_entry, ply)
            wb.save(opz.file_output)

            esito['fogli'].append("Entry List")

        log("Elaborazione torneo completata.")
    return esito


## DEMO ------------------------------------
def analizza_pdf_campionato(percorso_pdf: str, log=None):
    """
    Legge il PDF una sola volta, estrae i giocatori e restituisce 
    le informazioni sul campionato e le squadre disponibili.
    """
    lista_completa = _cs.leggi_lista(percorso_pdf, log)
    
    if not lista_completa:
        return {"errore": "Nessun giocatore trovato nel PDF."}
    
    
    info_campionato = lista_completa[0].etichetta # Es: "Serie B playoff/playout"
    
    squadre_disponibili = sorted(list(set(g.squadra for g in lista_completa if g.squadra)))
    
    return {
        "campionato": info_campionato,
        "numero_giocatori_totali": len(lista_completa),
        "squadre": squadre_disponibili,
        "dati_grezzi": lista_completa # Tieni questo in memoria (o in sessione) per usarlo dopo
    }


# avvio da terminale per provare la pipeline senza Flask e senza Selenium
#   Torneo:     python processor/main.py torneo <iscritti.xlsx> <tennis|beach> [doppio]
#   Campionato: python processor/main.py cs <lista.pdf> <dati_sgat.xlsx> "<squadra casa>" "<squadra ospite>"
if __name__ == "__main__":
    args = sys.argv[1:]
    stampa = lambda msg: print("  ·", msg)

    if len(args) >= 3 and args[0] == "torneo":
        _, iscritti, sport, *resto = args
        uscita = str(Path(iscritti).with_name(f"OUT_{sport}_{Path(iscritti).stem}.xlsx"))
        opz = TypeTorneo(file_iscritti=iscritti, file_output=uscita, sport=sport,
                         doppio="doppio" in resto, gen_ls=True, gen_prog=True)
        print(torneo(opz, log=stampa))

    elif len(args) == 5 and args[0] == "cs":
        _, pdf, sgat, casa, ospite = args
        info = analizza_pdf_campionato(pdf, log=stampa)
        print("Campionato:", info.get("campionato"), "| squadre:", len(info.get("squadre", [])))
        uscita = str(Path(sgat).with_name(f"OUT_cs_{Path(pdf).stem[:30]}.xlsx"))
        opz = TypeTorneo(file_iscritti=sgat, file_output=uscita, cs=True,
                         squadra_casa=casa, squadra_ospite=ospite,
                         lista_pdf=info.get("dati_grezzi", []))
        print(torneo(opz, log=stampa))

    else:
        print(__doc__)
        print('Uso:\n  python processor/main.py torneo <iscritti.xlsx> <tennis|beach> [doppio]\n'
              '  python processor/main.py cs <lista.pdf> <dati_sgat.xlsx> "<casa>" "<ospite>"')
