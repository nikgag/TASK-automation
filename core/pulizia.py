# Pulizia dei file temporanei di TASK.
"""Pulizia dei file temporanei: upload/ (file caricati, CON i dati dei giocatori) e output/ (Excel prodotti).

  pulisci_vecchi(giorni)  all'avvio di TASK: toglie quello che non viene modificato da più di `giorni` giorni
  svuota_tutto()          pulsante nell'index: toglie tutto subito
  dimensione()            quanti byte occupano adesso (per il pulsante)

data/campionati/: si tiene SEMPRE la lista più recente (è la "memoria" della pagina Campionato), le altre
seguono le stesse regole. Un file che non si può cancellare (es. un Excel aperto su Windows) viene saltato
e segnalato, senza fermare TASK: sono solo copie, al prossimo giro si riprova.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from core import conf


def _cartella_campionati() -> Path:
    return conf.DB_DIR / "campionati"


def _candidati() -> list[Path]:
    """Tutto quello che si può togliere: contenuto di upload/ e output/, liste campionato tranne l'ultima."""
    voci: list[Path] = []
    for cartella in (conf.UPLOAD_DIR, conf.OUTPUT_DIR):
        if cartella.is_dir():
            voci += sorted(cartella.iterdir())
    campionati = _cartella_campionati()
    if campionati.is_dir():
        liste = sorted(campionati.glob("*.csv"))     # stesso ordine con cui app.py sceglie la "memoria"
        voci += liste[:-1]
    return voci


def _ultima_modifica(voce: Path) -> float:
    """Per una cartella: il file più recente che contiene (la data della cartella cambia anche per poco)."""
    if voce.is_dir() and not voce.is_symlink():
        date = [p.stat().st_mtime for p in voce.rglob("*") if p.is_file() and not p.is_symlink()]
        return max(date, default=voce.stat().st_mtime)
    return voce.lstat().st_mtime


def _peso(voce: Path) -> int:
    if voce.is_dir() and not voce.is_symlink():
        return sum(p.stat().st_size for p in voce.rglob("*") if p.is_file() and not p.is_symlink())
    return voce.lstat().st_size


def _togli(voci: list[Path]) -> dict:
    esito = {"tolti": 0, "byte": 0, "saltati": []}
    for voce in voci:
        try:
            peso = _peso(voce)
            if voce.is_dir() and not voce.is_symlink():
                shutil.rmtree(voce)
            else:
                voce.unlink()
        except OSError as e:
            esito["saltati"].append(f"{voce.name} ({e.strerror or e})")
            continue
        esito["tolti"] += 1
        esito["byte"] += peso
    return esito


def pulisci_vecchi(giorni: int = conf.GIORNI_FILE_TEMPORANEI) -> dict:
    limite = time.time() - giorni * 86400
    return _togli([v for v in _candidati() if _ultima_modifica(v) < limite])


def svuota_tutto() -> dict:
    return _togli(_candidati())


def dimensione() -> int:
    return sum(_peso(v) for v in _candidati())


def in_mb(byte: int) -> str:
    return f"{byte / 1024 / 1024:.1f} MB".replace(".", ",")
