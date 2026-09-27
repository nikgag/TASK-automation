"""Avvio di TASK con un doppio clic.

Lo lanciano "Start TASK.command" (Mac) e "Start TASK.bat" (Windows): l'utente non
scrive nessun comando. Usa SOLO la libreria standard di Python, perché gira prima che le librerie
del progetto siano installate.

Cosa fa, in ordine:
  1. controlla che Python sia almeno 3.10;
  2. al primo avvio crea l'ambiente .venv/ nella cartella del progetto e installa requirements.txt
     (serve internet, qualche minuto). Se requirements.txt cambia, reinstalla da solo;
  3. se FITP Manager è già aperto, riapre solo il browser (niente doppio avvio);
  4. sceglie la porta (5050, o la prima libera dopo) e avvia core/app.py con l'ambiente .venv;
     app.py apre il browser di sistema.
Per chiudere il programma basta chiudere la finestra del terminale che si apre col doppio clic.
"""
import hashlib
import os
import socket
import subprocess
import sys
import urllib.request
import venv
import webbrowser
from pathlib import Path

CARTELLA = Path(__file__).resolve().parent
VENV = CARTELLA / ".venv"
REQUISITI = CARTELLA / "requirements.txt"
MARCA = VENV / "requisiti_installati.txt"        # impronta del requirements.txt già installato
WINDOWS = os.name == "nt"
PYTHON_VENV = VENV / ("Scripts/python.exe" if WINDOWS else "bin/python")

sys.path.insert(0, str(CARTELLA))
from core import conf                             # conf.py usa solo pathlib: si importa anche qui


def messaggio_fatale(testo: str) -> None:
    """Errore che impedisce l'avvio: lo scrive nella finestra e, sul Mac, lo mostra anche in un riquadro."""
    print("\n" + "=" * 70 + "\n" + testo + "\n" + "=" * 70)
    if sys.platform == "darwin":
        testo_as = testo.replace("\\", "\\\\").replace('"', '\\"')
        subprocess.call(["osascript", "-e",
                         f'display dialog "{testo_as}" with title "FITP Manager" buttons {{"OK"}} with icon stop'],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        input("\nPremi Invio per chiudere...")
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
    esito = subprocess.call([str(PYTHON_VENV), "-m", "pip", "install", "--disable-pip-version-check",
                             "-r", str(REQUISITI)])
    if esito != 0:
        messaggio_fatale("Installazione delle librerie non riuscita.\n"
                         "Controlla la connessione a internet e riapri il programma.\n"
                         "Se continua a non funzionare, cancella la cartella nascosta .venv del progetto e riprova.\n"
                         "(Il dettaglio dell'errore è nella finestra del terminale.)")
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
        print("ATTENZIONE: non trovo Google Chrome. Il controllo delle tessere lo usa:\n"
              "installalo da https://www.google.com/chrome/ prima di avviare un'elaborazione.\n")


def main() -> None:
    os.chdir(CARTELLA)
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
    print("  Per CHIUDERE il programma chiudi questa finestra.")
    print("-" * 70 + "\n")
    ambiente = dict(os.environ, FITP_PORTA=str(porta), PYTHONUNBUFFERED="1")
    try:
        sys.exit(subprocess.call([str(PYTHON_VENV), str(CARTELLA / "core" / "app.py")], env=ambiente))
    except KeyboardInterrupt:
        print("\nFITP Manager chiuso.")


if __name__ == "__main__":
    main()
