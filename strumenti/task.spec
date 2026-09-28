# -*- mode: python ; coding: utf-8 -*-
# Comm. Claude: ricetta PyInstaller dell'exe (la usa strumenti/crea_installer_windows.bat).
# Produce dist/TASK/ (TASK.exe + _internal/): cartella "onedir", che poi Inno Setup impacchetta in TASK-Setup.exe.
# Onedir e non onefile: onefile a ogni avvio estrarrebbe ~200 MB in una cartella temporanea (avvio lento).
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

PROGETTO = Path(SPECPATH).parent          # SPECPATH = cartella di questo file (strumenti/)
DATA = PROGETTO / "data"

# circolo_regioni.csv non è su git (dati FITP riservati) ma va nell'installer: senza, ci si ferma subito.
if not (DATA / "circolo_regioni.csv").is_file():
    sys.exit(f"ERRORE: manca {DATA / 'circolo_regioni.csv'}: copialo in data/ prima di creare l'installer.")

# data/: solo i file (niente archivio/ né file nascosti). Nell'exe sono copie di partenza: avvia.py le copia
# nella cartella dell'utente al primo avvio, senza mai sovrascrivere quelle già presenti.
dati_iniziali = [(str(f), "data") for f in sorted(DATA.iterdir())
                 if f.is_file() and not f.name.startswith(".") and f.suffix in {".csv", ".xlsx", ".json"}]

a = Analysis(
    [str(PROGETTO / "avvia.py")],
    pathex=[str(PROGETTO)],
    datas=[
        (str(PROGETTO / "templates"), "templates"),
        (str(PROGETTO / "static"), "static"),
        (str(PROGETTO / "codici_errori.csv"), "."),
        *dati_iniziali,
        *collect_data_files("pdfminer"),   # tabelle dei caratteri usate da pdfplumber per leggere i PDF
    ],
    # core.app si importa dentro una funzione di avvia.py: elenco esplicito per non perdere nessun modulo
    hiddenimports=collect_submodules("core") + collect_submodules("processor"),
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TASK",
    console=False,          # nessuna finestra del terminale
    upx=False,              # UPX fa scattare più spesso i falsi allarmi degli antivirus
)
coll = COLLECT(exe, a.binaries, a.datas, name="TASK", upx=False)
