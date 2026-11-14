# -*- mode: python ; coding: utf-8 -*-
# ricetta PyInstaller dell'exe (la usa strumenti/crea_installer_windows.bat).
# Produce dist/TASK/ (TASK.exe + _internal/): cartella "onedir", che poi Inno Setup impacchetta in TASK-Setup.exe.
# Onedir e non onefile: onefile a ogni avvio estrarrebbe ~200 MB in una cartella temporanea (avvio lento).
import sys
from pathlib import Path
# collect_all: serve per selenium (sottomoduli caricati in lazy + selenium-manager.exe)
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_all

PROGETTO = Path(SPECPATH).parent          # SPECPATH = cartella di questo file (strumenti/)
DATA = PROGETTO / "data"

# circolo_regioni.csv NON va più nell'exe: i circoli sono nel DB online (processor/circoli_db.py)
# e il file contiene dati FITP riservati. Escluso anche se è presente in data/ (build locale).
ESCLUSI = {"circolo_regioni.csv"}

# data/: solo i file (niente archivio/ né file nascosti). Nell'exe sono copie di partenza: avvia.py le copia
# nella cartella dell'utente al primo avvio, senza mai sovrascrivere quelle già presenti.
dati_iniziali = [(str(f), "data") for f in sorted(DATA.iterdir())
                 if f.is_file() and not f.name.startswith(".") and f.suffix in {".csv", ".xlsx", ".json"}
                 and f.name not in ESCLUSI]

# selenium carica i sottomoduli a runtime (importlib, es. selenium.webdriver.chrome.webdriver):
# l'analisi statica di PyInstaller non li vede, quindi li dichiaro. Porta dentro anche selenium-manager.exe
sel_datas, sel_binaries, sel_hidden = collect_all("selenium")

a = Analysis(
    [str(PROGETTO / "avvia.py")],
    pathex=[str(PROGETTO)],
    binaries=sel_binaries,   # selenium-manager.exe (scarica il driver di Chrome)
    datas=[
        (str(PROGETTO / "templates"), "templates"),
        (str(PROGETTO / "static"), "static"),
        (str(PROGETTO / "codici_errori.csv"), "."),
        *dati_iniziali,
        *collect_data_files("pdfminer"),   # tabelle dei caratteri usate da pdfplumber per leggere i PDF
        *sel_datas,                        # file dati di selenium
    ],
    # core.app si importa dentro una funzione di avvia.py: elenco esplicito per non perdere nessun modulo
    hiddenimports=(
        collect_submodules("core") + collect_submodules("processor")
        + sel_hidden                                # sottomoduli di selenium
        # pandas carica i motori Excel a runtime (read_excel): openpyxl per .xlsx, xlrd per .xls
        + collect_submodules("pandas.io.excel")
        + collect_submodules("openpyxl")
        + ["xlrd"]
    ),
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
