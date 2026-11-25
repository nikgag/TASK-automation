# Quote FIT impostate dall'utente (cambiano ogni anno).
"""Impostazioni dell'utente, salvate su questo computer FUORI dalla cartella del progetto
(conf.IMPOSTAZIONI_UTENTE, accanto al codice di accesso): non finiscono mai nel repo.

  quote()              {"under", "over", "anno", "impostate"}: quelle salvate, oppure i valori di conf.py
  salva_quote(u, o)    salva (con l'anno corrente) e applica subito
  applica()            copia le quote salvate in conf.QUOTA_FIT_UNDER / conf.QUOTA_FIT_OVER:
                       contatti.calcola_quota le legge da lì, quindi contatti.py non cambia
Le quote si cambiano nel modulo del torneo (sezione "Quota d'iscrizione"): le caselle partono con le
ultime salvate e, quando il torneo parte, i valori del modulo vengono salvati per la volta successiva.
"""
from __future__ import annotations

import json
import os
from datetime import date

from core import conf
from core.errori import ErroreUtente

# valori di partenza (conf.py), presi PRIMA che applica() li sovrascriva
PREDEFINITE = {"under": conf.QUOTA_FIT_UNDER, "over": conf.QUOTA_FIT_OVER}
MAX_QUOTA = 100.0


def _leggi() -> dict:
    if not conf.IMPOSTAZIONI_UTENTE.is_file():
        return {}
    try:
        return json.loads(conf.IMPOSTAZIONI_UTENTE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise RuntimeError(f"File delle impostazioni rovinato: {conf.IMPOSTAZIONI_UTENTE} ({e}). "
                           f"Cancellalo: TASK chiederà di nuovo le quote FIT.") from e


def quote() -> dict:
    salvate = _leggi().get("quote_fit")
    if not salvate:
        return {**PREDEFINITE, "anno": None, "impostate": False}
    return {"under": float(salvate["under"]), "over": float(salvate["over"]),
            "anno": int(salvate["anno"]), "impostate": True}


def salva_quote(under: float, over: float) -> None:
    for nome, valore in (("Under", under), ("Over", over)):
        if not 0 <= valore <= MAX_QUOTA:
            raise ErroreUtente(f"Err 66: quota FIT {nome} non valida ({valore}): deve essere tra 0 e {MAX_QUOTA:.0f} €.")
    dati = _leggi()
    dati["quote_fit"] = {"under": round(under, 2), "over": round(over, 2), "anno": date.today().year}
    conf.IMPOSTAZIONI_UTENTE.parent.mkdir(parents=True, exist_ok=True)
    temporaneo = conf.IMPOSTAZIONI_UTENTE.with_suffix(".tmp")
    temporaneo.write_text(json.dumps(dati, indent=2), encoding="utf-8")
    os.replace(temporaneo, conf.IMPOSTAZIONI_UTENTE)
    applica()


def applica() -> None:
    q = quote()
    conf.QUOTA_FIT_UNDER, conf.QUOTA_FIT_OVER = q["under"], q["over"]
