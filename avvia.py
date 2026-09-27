"""Avvio di TASK con un doppio clic.

Lo lanciano "Start TASK.app" (Mac) e "Start TASK.vbs" (Windows) SENZA finestra del terminale: l'utente non
scrive nessun comando e non vede console. I messaggi finiscono in avvio.log, gli errori in un riquadro. Usa SOLO la libreria standard di Python, perché gira prima che le librerie
del progetto siano installate.

Nell'exe per Windows (PyInstaller, vedi strumenti/) è il punto d'ingresso: salta .venv e pip, copia i dati
iniziali nella cartella dell'utente e avvia il server nello stesso processo.  #Comm. Claude:  paragrafo nuovo

Cosa fa, in ordine:
  1. controlla che Python sia almeno 3.10;
  2. al primo avvio crea l'ambiente .venv/ nella cartella del progetto e installa requirements.txt
     (serve internet, qualche minuto). Se requirements.txt cambia, reinstalla da solo;
  3. se FITP Manager è già aperto, riapre solo il browser (niente doppio avvio);
  4. sceglie la porta (5050, o la prima libera dopo) e avvia core/app.py con l'ambiente .venv;
     app.py apre il browser di sistema.
Per chiudere il programma basta chiudere la pagina nel browser.
"""
#Comm. Claude:  docstring: lanciatori nuovi (.app/.vbs) senza terminale, quindi niente "chiudi la finestra".
#Comm. Claude:  docstring aggiornata: ora il processo termina anche chiudendo la pagina (watchdog in core/app.py).
#Comm. Claude:  heartbeat/watchdog NON stanno qui: avvia.py gira col Python di sistema, senza flask/waitress.
import hashlib
import os
import shutil   #Comm. Claude:  per copiare i dati iniziali nell'exe
import socket
import subprocess
import sys
import urllib.request
import venv
import threading   #Comm. Claude:  per i riquadri Windows che non bloccano
import time        #Comm. Claude:  data e ora nell'intestazione di ogni avvio in avvio.log
import webbrowser
from pathlib import Path

CARTELLA = Path(__file__).resolve().parent
VENV = CARTELLA / ".venv"
REQUISITI = CARTELLA / "requirements.txt"
MARCA = VENV / "requisiti_installati.txt"        # impronta del requirements.txt già installato
WINDOWS = os.name == "nt"
PYTHON_VENV = VENV / ("Scripts/python.exe" if WINDOWS else "bin/python")
#Comm. Claude:  senza terminale i print non li vede nessuno: vanno in avvio.log (sovrascritto a ogni avvio)
USCITA: dict = {}                                 # stdout/stderr per pip e app.py: vuoto = come il terminale
DOVE_DETTAGLI = "Il dettaglio dell'errore è nella finestra del terminale."
#Comm. Claude:  su Windows ogni sottoprocesso python.exe aprirebbe una console nera: CREATE_NO_WINDOW la evita
NASCOSTO = {"creationflags": subprocess.CREATE_NO_WINDOW} if WINDOWS else {}

sys.path.insert(0, str(CARTELLA))
from core import conf                             # conf.py usa solo la libreria standard: si importa anche qui
#Comm. Claude:  il log sta tra i dati (cartella del progetto da sorgente, AppData/Local/TASK nell'exe); in coda (append):
#Comm. Claude:  un secondo doppio clic con TASK già aperto non deve troncare il log in uso
LOG = conf.DATI_DIR / "avvio.log"
LOG_MAX = 1_000_000                               # byte: oltre, il vecchio diventa avvio.log.old


#Comm. Claude:  funzione nuova
def prepara_log() -> None:
    """Senza terminale (doppio clic su .app/.vbs) i messaggi vanno in avvio.log.

    Con un terminale (sviluppatore che lancia `python3 avvia.py`) resta tutto come prima.
    """
    global DOVE_DETTAGLI
    if sys.stdout is not None and sys.stdout.isatty():
        return
    LOG.parent.mkdir(parents=True, exist_ok=True)   #Comm. Claude:  nell'exe al primo avvio la cartella dati non esiste ancora
    if LOG.is_file() and LOG.stat().st_size > LOG_MAX:
        LOG.replace(LOG.with_suffix(".log.old"))
    registro = open(LOG, "a", encoding="utf-8", buffering=1)   # buffering=1: riga per riga, niente perso se crasha
    registro.write(f"\n===== avvio {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
    sys.stdout = sys.stderr = registro
    USCITA.update(stdout=registro, stderr=subprocess.STDOUT)
    DOVE_DETTAGLI = f"Il dettaglio è nel file:\n{LOG}"   #Comm. Claude:  percorso completo: nell'exe non è nella cartella del programma


#Comm. Claude:  funzione nuova
def finestra(testo: str, errore: bool = False, attendi: bool = True) -> None:
    """Riquadro di sistema (Mac: osascript, Windows: MessageBox), unico canale visibile senza terminale.

    attendi=False: il riquadro resta aperto ma il programma va avanti (avvisi informativi).
    """
    print("\n" + "=" * 70 + "\n" + testo + "\n" + "=" * 70, flush=True)   # anche nel log/terminale
    if sys.platform == "darwin":
        testo_as = testo.replace("\\", "\\\\").replace('"', '\\"')
        icona = "stop" if errore else "note"
        comando = ["osascript", "-e", f'display dialog "{testo_as}" with title "TASK" '
                                      f'buttons {{"OK"}} default button 1 with icon {icona}']
        (subprocess.call if attendi else subprocess.Popen)(comando, stdout=subprocess.DEVNULL,
                                                           stderr=subprocess.DEVNULL)
    elif WINDOWS:
        import ctypes
        stile = (0x10 if errore else 0x40) | 0x40000     # icona errore/informazione, sempre in primo piano
        mostra = lambda: ctypes.windll.user32.MessageBoxW(None, testo, "TASK", stile)
        mostra() if attendi else threading.Thread(target=mostra, daemon=True).start()
    elif attendi and sys.stdin is not None and sys.stdin.isatty():
        input("\nPremi Invio per chiudere...")


def messaggio_fatale(testo: str) -> None:
    """Errore che impedisce l'avvio: riquadro di errore e uscita."""
    finestra(testo, errore=True)   #Comm. Claude:  prima solo il Mac aveva il riquadro; Windows usava input(), impossibile senza console
    sys.exit(1)


def controlla_python() -> None:
    if sys.version_info < (3, 10):
        messaggio_fatale(f"TASK richiede Python 3.10 o più recente (questo è {sys.version.split()[0]}).\n"
                         "Scarica l'ultima versione da https://www.python.org/downloads/ e riapri il programma.")


def impronta_requisiti() -> str:
    return hashlib.sha256(REQUISITI.read_bytes()).hexdigest()


def prepara_ambiente() -> None:
    """Crea .venv/ e installa le librerie, solo se serve."""
    if not PYTHON_VENV.is_file():
        print("Primo avvio: preparo l'ambiente del programma (serve internet, qualche minuto)...")
        venv.create(VENV, with_pip=True)
    if MARCA.is_file() and MARCA.read_text().strip() == impronta_requisiti():
        return
    print("Installo le librerie necessarie (flask, pandas, selenium, ...)...\n")
    if USCITA:   #Comm. Claude:  senza terminale l'utente non vedrebbe nulla per minuti: avviso che non blocca
        finestra("Preparo TASK: installo le librerie necessarie.\n\n"
                 "Serve internet e può richiedere qualche minuto: la pagina si aprirà da sola.", attendi=False)
    ambiente = dict(os.environ, PYTHONIOENCODING="utf-8")   #Comm. Claude:  log in utf-8 anche su Windows (lettere accentate)
    esito = subprocess.call([str(PYTHON_VENV), "-m", "pip", "install", "--disable-pip-version-check",
                             "-r", str(REQUISITI)], env=ambiente, **USCITA, **NASCOSTO)
    if esito != 0:
        messaggio_fatale("Installazione delle librerie non riuscita.\n"
                         "Controlla la connessione a internet e riapri il programma.\n"
                         "Se continua a non funzionare, cancella la cartella nascosta .venv del progetto e riprova.\n"
                         f"({DOVE_DETTAGLI})")   #Comm. Claude:  il terminale può non esserci più
    MARCA.write_text(impronta_requisiti())
    print("\nLibrerie installate.\n")


def fitp_gia_aperto(porta: int) -> bool:
    """True se su quella porta risponde proprio FITP Manager (e non un altro programma)."""
    # riconosce l'app dall'intestazione X-FITP-Manager, non dal nome nella pagina
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{porta}/", timeout=2) as risposta:
            return risposta.headers.get("X-FITP-Manager") == "1"
    except Exception:
        return False


def porta_libera(porta: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", porta)) != 0


def scegli_porta() -> tuple:
    """(porta, già_aperto). Prima la porta di conf.py, poi le 20 successive."""
    for porta in range(conf.PORTA_GUI, conf.PORTA_GUI + 20):
        if fitp_gia_aperto(porta):
            return porta, True
        if porta_libera(porta):
            return porta, False
    messaggio_fatale(f"Nessuna porta libera tra {conf.PORTA_GUI} e {conf.PORTA_GUI + 19}.")


def avvisa_se_manca_chrome() -> None:
    """Il controllo tessere usa Google Chrome: se non lo trovo avviso (senza bloccare)."""
    possibili = {
        "darwin": ["/Applications/Google Chrome.app", str(Path.home() / "Applications/Google Chrome.app")],
        "win32": [os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
                  os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
                  os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe")],
    }.get(sys.platform)
    if possibili and not any(Path(p).exists() for p in possibili):
        finestra("ATTENZIONE: non trovo Google Chrome. Il controllo delle tessere lo usa:\n"   #Comm. Claude:  riquadro, non print
                 "installalo da https://www.google.com/chrome/ prima di avviare un'elaborazione.", attendi=False)


#Comm. Claude:  funzione nuova. Nell'exe i file di data/ inclusi nell'installer sono solo copie di partenza:
#Comm. Claude:  li copio nella cartella dati solo se mancano, così non sovrascrivo MAI circoli aggiunti o coefficienti aggiornati.
def copia_dati_iniziali() -> None:
    conf.DB_DIR.mkdir(parents=True, exist_ok=True)
    for sorgente in conf.DATI_INIZIALI_DIR.iterdir():
        destinazione = conf.DB_DIR / sorgente.name
        if sorgente.is_file() and not destinazione.exists():
            shutil.copy2(sorgente, destinazione)
            print(f"Primo avvio: copiato {sorgente.name} in {conf.DB_DIR}")


def main() -> None:
    #Comm. Claude:  nell'exe si lavora nella cartella dati; da sorgente nella cartella del progetto (come prima)
    conf.DATI_DIR.mkdir(parents=True, exist_ok=True)
    os.chdir(conf.DATI_DIR if conf.CONGELATO else CARTELLA)
    prepara_log()   #Comm. Claude:  per primo: da qui in poi ogni messaggio ha una destinazione
    #Comm. Claude:  conferma al lanciatore Mac che sono partito davvero (cartella leggibile, permessi macOS ok)
    if os.environ.get("TASK_SEGNALE"):
        Path(os.environ["TASK_SEGNALE"]).touch()
    if conf.CONGELATO:   #Comm. Claude:  nell'exe Python e librerie sono già dentro: niente .venv né pip
        copia_dati_iniziali()
    else:
        controlla_python()
        prepara_ambiente()
    porta, gia_aperto = scegli_porta()
    indirizzo = f"http://127.0.0.1:{porta}"
    if gia_aperto:
        print(f"FITP Manager è già aperto: riapro il browser su {indirizzo}")
        webbrowser.open(indirizzo)
        return
    avvisa_se_manca_chrome()
    print("-" * 70)
    print(f"  FITP Manager si apre nel browser: {indirizzo}")
    print("  Per CHIUDERE il programma chiudi la pagina nel browser.")  #Comm. Claude:  il watchdog di core/app.py spegne il processo
    print("-" * 70 + "\n")
    if conf.CONGELATO:
        #Comm. Claude:  nell'exe non c'è un python.exe da lanciare: il server gira in questo stesso processo
        from core import app as programma
        programma.avvia_server(porta)   # ritorna solo se il server si ferma; di norma il watchdog chiude prima il processo
        return
    ambiente = dict(os.environ, FITP_PORTA=str(porta), PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
    try:
        codice = subprocess.call([str(PYTHON_VENV), str(CARTELLA / "core" / "app.py")], env=ambiente,
                                 **USCITA, **NASCOSTO)
    except KeyboardInterrupt:
        print("\nTASK chiuso.")
        return
    #Comm. Claude:  0 = spento dal watchdog (pagina chiusa). Altro = app.py è crollato: senza terminale va detto a voce alta
    if codice != 0:
        messaggio_fatale(f"TASK si è chiuso per un errore (codice {codice}).\n\n{DOVE_DETTAGLI}")


if __name__ == "__main__":
    #Comm. Claude:  un errore imprevisto qui, senza terminale, sparirebbe in silenzio: riquadro + traceback nel log, poi rilancio
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        finestra(f"Errore imprevisto all'avvio di TASK:\n{type(e).__name__}: {e}\n\n{DOVE_DETTAGLI}", errore=True)
        if conf.CONGELATO:   #Comm. Claude:  nell'exe un raise farebbe comparire un secondo riquadro (quello di PyInstaller)
            sys.exit(1)
        raise
