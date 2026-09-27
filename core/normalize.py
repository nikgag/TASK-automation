"""Normalizzazioni condivise.

Queste funzioni erano ripetute (copia-incolla o riscritte) in piu' script:
- normalizzazione nome/cognome per il matching
- normalizzazione numero tessera (zfill a 10, gestione del ".0")
- normalizzazione classifica (virgola -> punto)
- costruzione del link tessera FITP

Raccogliendole qui evitiamo divergenze e bug sottili tra gli script.
"""
from __future__ import annotations

from urllib.parse import urlencode

from . import conf as config

# Mappa accenti -> lettere semplici, per il matching dei nomi.
_ACCENTI = str.maketrans({
    "à": "a", "á": "a",
    "è": "e", "é": "e",
    "ì": "i", "í": "i",
    "ò": "o", "ó": "o",
    "ù": "u", "ú": "u",
})


def normalizza_nome(testo) -> str:
    """Minuscolo, senza spazi ai bordi e senza accenti. '' se vuoto/NaN."""
    if testo is None:
        return ""
    t = str(testo).strip()
    if t == "" or t.lower() == "nan":
        return ""
    return t.lower().translate(_ACCENTI)


def normalizza_tessera(valore) -> str:
    """Numero tessera a 10 cifre.

    Gestisce i casi reali: numero float da Excel (2205401897.0), stringa con
    ".0", testo con spazi. Restituisce '' se non convertibile.
    """
    if valore is None:
        return ""
    testo = str(valore).strip()
    if testo == "" or testo.lower() == "nan":
        return ""
    try:
        # copre sia "2205401897" sia "2205401897.0" sia 2205401897.0
        return str(int(float(testo))).zfill(10)
    except (ValueError, TypeError):
        return testo.replace(".0", "").zfill(10)


def normalizza_classifica(valore) -> str:
    """Classifica come stringa con il punto decimale (es. '3.2')."""
    if valore is None:
        return ""
    testo = str(valore).strip()
    if testo.lower() == "nan":
        return ""
    return testo.replace(",", ".")


def normalizza_telefono(valore) -> str:
    """Numero di telefono in sole cifre. '' se non valido."""
    if valore is None:
        return ""
    testo = str(valore).strip()
    if testo == "" or testo.lower() == "nan":
        return ""
    try:
        return str(int(float(testo)))          # gestisce 3357815259.0
    except (ValueError, TypeError):
        # tiene solo le cifre (toglie +, spazi, ecc.)
        return "".join(c for c in testo if c.isdigit())


def link_tessera(num_tessera) -> str:
    """URL della tessera FITP per un dato numero. Un solo punto di verita'."""
    tessera = normalizza_tessera(num_tessera)
    query = urlencode({"k": tessera, **config.FITP_TESSERA_QUERY})
    return f"{config.FITP_TESSERA_BASE_URL}?{query}"
