"""Foglio "Contatti": telefono, email, categoria, quota, link WhatsApp.

Unifica la versione di file_torneo.py (tennis, con calcolo quota) e crea_entry.py
(beach, senza quota). La quota si attiva con `con_quota=True`.
"""
from __future__ import annotations

import urllib.parse

from core import conf as config, excel_style, normalize

COLONNE_CON_QUOTA = ["Cognome", "Nome", "Telefono", "Email", "Cat. Età", "Quota", "WhatsApp"]
COLONNE_SENZA_QUOTA = ["Cognome", "Nome", "Telefono", "Email", "Cat. Età", "WhatsApp"]


def calcola_quota(categoria: str, quota_under: float, quota_over: float) -> float:
    """Quota d'iscrizione: quota FIT + supplemento under/over.

    Under = categorie giovanili (U10..U16), altrimenti Over.
    """
    if str(categoria).strip().upper() in config.CATEGORIE_UNDER:
        return config.QUOTA_FIT_UNDER + quota_under
    return config.QUOTA_FIT_OVER + quota_over


def link_whatsapp(telefono: str, messaggio: str = "") -> str:
    """Link 'click-to-chat' di WhatsApp per un numero (solo cifre)."""
    tel = normalize.normalizza_telefono(telefono)
    url = f"https://web.whatsapp.com/send?phone={tel}"
    if messaggio:
        url += f"&text={urllib.parse.quote(messaggio)}"
    return url


def scrivi_foglio_contatti(ws, df_iscritti, con_quota: bool = False,
                           quota_under: float = 0.0, quota_over: float = 0.0,
                           messaggio: str = "", log=None) -> None:
    """Scrive il foglio Contatti con link WhatsApp cliccabili (e quota se richiesto)."""
    log = log or (lambda *a: None)
    colonne = COLONNE_CON_QUOTA if con_quota else COLONNE_SENZA_QUOTA
    ws.append(colonne)
    excel_style.formatta_file(ws, colore_header=config.COLORE_HEADER)
    wa_col = colonne.index("WhatsApp") + 1

    for _, row in df_iscritti.iterrows():
        cognome = str(row.get("Cognome", ""))
        telefono = normalize.normalizza_telefono(row.get("Telefono"))
        if not telefono:
            log(f"Att. 06: numero di telefono di {cognome} mancante o non valido.")
        categoria = row.get("Cat. Età", "")

        valori = [cognome, str(row.get("Nome", "")), telefono,
                  row.get("Email", ""), categoria]
        if con_quota:
            valori.append(calcola_quota(categoria, quota_under, quota_over))
        valori.append(f'=HYPERLINK("{link_whatsapp(telefono, messaggio)}", "Chat {cognome}")')

        ws.append(valori)
        cell = ws.cell(row=ws.max_row, column=wa_col)
        cell.font = excel_style.FONT_LINK
