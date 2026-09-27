"""File CSV per il Live Score.

Estratto da file_torneo.py. Genera un CSV con LastName, FirstName, IOCCode, e
l'EventShortcut (F/M), dedotto dal nome del file iscritti o passato esplicitamente.
"""
from __future__ import annotations

import csv

IOC_DEFAULT = "ITA"


def deduci_evento(nome_file: str) -> str | None:
    """Deduce l'EventShortcut dal nome del file: 'F' femminile, 'M' maschile, None se ignoto."""
    testo = str(nome_file).lower()
    if "femminile" in testo:
        return "F"
    if "maschile" in testo:
        return "M"
    return None


def scrivi_csv_live_score(df_iscritti, percorso_csv, evento: str,
                          ioc: str = IOC_DEFAULT) -> int:
    """Scrive il CSV del live score. Restituisce il numero di righe scritte."""
    righe = 0
    with open(percorso_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f, fieldnames=["LastName", "FirstName", "IOCCode", "EventShortcut"]
        )
        writer.writeheader()
        for _, row in df_iscritti.iterrows():
            writer.writerow({
                "LastName": row.get("Cognome", ""),
                "FirstName": row.get("Nome", ""),
                "IOCCode": ioc,
                "EventShortcut": evento,
            })
            righe += 1
    return righe
