"""Codici d'errore e distinzione tra errori dell'UTENTE ed errori del PROGRAMMA.

  - ErroreUtente: il problema sta in un file o in una scelta dell'utente (Excel senza colonne, PDF
    sbagliato…). L'app NON salta: mostra il messaggio con "Cosa fare" e riporta al modulo.
  - Qualsiasi altro errore è un errore del PROGRAMMA: ferma tutto e mostra il
    traceback (debugger con FITP_DEBUG=1, pagina errore.html altrimenti).
  - Causa e "Cosa fare" di ogni codice stanno in codici_errori.csv (cartella del progetto, si apre
    con Excel). È l'unico posto da aggiornare: le pagine leggono i testi da lì.
"""
from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path

from core import conf


class ErroreUtente(ValueError):
    """Errore nei dati o nei file dell'utente: messaggio chiaro, niente crash."""


_RE_CODICE = re.compile(r"\b(Err|Att\.) ?(\d{2})\b")


def codice_di(messaggio) -> str | None:
    """'Err 31: nel foglio…' -> 'Err 31'  (None se il messaggio non ha codice)."""
    m = _RE_CODICE.search(str(messaggio))
    return f"{m.group(1)} {m.group(2)}" if m else None


@lru_cache(maxsize=1)
def tabella() -> dict[str, dict]:
    """codici_errori.csv -> {"Err 31": {"Tipo": …, "Causa": …, "Cosa fare": …}, …}"""
    with open(conf.CODICI_ERRORI, encoding="utf-8-sig", newline="") as f:
        return {riga["Codice"].strip(): riga for riga in csv.DictReader(f, delimiter=";")}


def cosa_fare(messaggio) -> str:
    """Il suggerimento per l'utente associato al codice contenuto nel messaggio ('' se non c'è)."""
    codice = codice_di(messaggio)
    return tabella().get(codice, {}).get("Cosa fare", "") if codice else ""


def codici_non_documentati() -> list[str]:
    """Codici scritti nel codice Python ma assenti da codici_errori.csv (controllo per lo sviluppatore)."""
    usati: set[str] = set()
    for cartella in ("core", "processor"):
        for py in (conf.BASE_DIR / cartella).glob("*.py"):
            usati |= {f"{a} {b}" for a, b in _RE_CODICE.findall(py.read_text(encoding="utf-8"))}
    return sorted(usati - set(tabella()))
