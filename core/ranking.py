"""Mappe classifiche <-> valori numerici RTS (per il seeding / posizionamento).

ATTENZIONE: tennis e beach tennis usano DUE scale diverse.
- TENNIS  (ex doppi.py): scala completa 2.1-2.8 / 3.1-3.5 / 4.1-4.6  -> 18..40
- BEACH   (ex crea_entry.py): scala compressa 2.1-2.4 / 3.1-3.4 / 4.NC -> 18..33

Nel doppio, la SOMMA dei valori della coppia ne determina la forza e quindi
il posizionamento in tabellone (valore piu' basso = coppia piu' forte).
Le chiavi usano il punto come separatore (coerente con normalize.normalizza_classifica).
"""
from __future__ import annotations
import pandas as pd
from core import conf

# --- TENNIS (scala completa FITP RTS) -----------------------------------------
MAPPA_VALORI_TENNIS: dict[str, int] = {
    "1.1": 18,
    "2.1": 21, "2.2": 22, "2.3": 23, "2.4": 24,
    "2.5": 25, "2.6": 26, "2.7": 27, "2.8": 28,
    "3.1": 29, "3.2": 30, "3.3": 31, "3.4": 32, "3.5": 33,
    "4.1": 34, "4.2": 35, "4.3": 36, "4.4": 37, "4.5": 38, "4.6": 39, "4.NC": 40,
}

# --- BEACH TENNIS (scala compressa) -------------------------------------------
MAPPA_VALORI_BEACH: dict[str, int] = {
    "1.1": 18,
    "2.1": 21, "2.2": 22, "2.3": 23, "2.4": 24,
    "3.1": 25, "3.2": 26, "3.3": 27, "3.4": 28,
    "4.1": 29, "4.2": 30, "4.3": 31, "4.4": 32, "4.NC": 33,
}

# Selettore per sport.
MAPPE = {"tennis": MAPPA_VALORI_TENNIS, "beach": MAPPA_VALORI_BEACH}

# Valore usato quando una classifica non e' in mappa (spinge in fondo).
VALORE_SCONOSCIUTO = 100


def mappa_per_sport(sport: str) -> dict[str, int]:
    """Restituisce la mappa RTS corretta per 'tennis' o 'beach'."""
    try:
        return MAPPE[sport]
    except KeyError:
        raise ValueError(f"Sport non valido: {sport!r} (usa 'tennis' o 'beach')")

#forse tirare via sport
def valore_classifica(classifica: str, sport: str = "beach",
                      default: int = VALORE_SCONOSCIUTO) -> int: 
    """Valore numerico di una classifica per lo sport indicato; default se assente."""
    return mappa_per_sport(sport).get(str(classifica), default)


def valore_coppia(classifica_a: str, classifica_b: str, sport: str = "tennis") -> int:
    """Somma dei valori RTS di una coppia (forza della coppia per il seeding).

    Valore piu' basso = coppia piu' forte = testa di serie piu' alta.
    """
    mappa = mappa_per_sport(sport)
    va = mappa.get(str(classifica_a), VALORE_SCONOSCIUTO)
    vb = mappa.get(str(classifica_b), VALORE_SCONOSCIUTO)
    return va + vb


def to_float(val) -> float:
    """Converte in float gestendo la virgola decimale ('3,2' -> 3.2)."""
    if isinstance(val, str):
        return float(val.replace(",", "."))
    return float(val)

def safe_float(val) -> float:
    """Converte in float senza mai sollevare eccezioni (0.0 in caso d'errore)."""
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0

def ass_coeff(giocatore, circolo, df, rank_default=""):
    # Match persona
    # '_key' = nome normalizzato, creato da players.df_coeff
    col_nome = '_key' if '_key' in df.columns else 'Tesserato'
    match_DB = df[df[col_nome] == giocatore]
    
    if match_DB.empty: 
        coeff = 0.0
        classifica = rank_default
    else: 
        if len(match_DB) == 1:
            data = match_DB.iloc[0]
        else:
            club_match = match_DB[match_DB['Società'].astype(str).str.strip().str.upper()
                                  == str(circolo).strip().upper()]
            data = club_match.iloc[0] if not club_match.empty else match_DB.iloc[0]
        
        # Estrazione dati
        coeff = data.get('Coeff', 0.0)
        promo = data.get('Classifica promozione', 0)
        
        if pd.notna(promo) and str(promo).strip() not in ("", "0"):
            classifica = promo
        else:
            # nel CSV la colonna è 'Class' (senza punto); se è vuota resta la classifica SGAT
            classifica = data.get('Class', data.get('Class.', rank_default))
            if pd.isna(classifica) or str(classifica).strip() == "":
                classifica = rank_default
            
    # Pulizia e conversione numerica di coeff
    if isinstance(coeff, str):
        coeff = coeff.strip().replace(',', '.')
        try:
            coeff = float(coeff)
        except ValueError:
            coeff = 0.0
    else:
        try:
            coeff = float(coeff) if pd.notna(coeff) else 0.0
        except (ValueError, TypeError):
            coeff = 0.0
            
    return coeff, classifica
        
    