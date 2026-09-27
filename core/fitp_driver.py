"""Driver Selenium per le tessere FITP (ex tessere_driver.py).

Struttura invariata rispetto all'originale (era gia' fatto bene, in classe):
carica la pagina UNA volta e legge tutti i campi necessari. Piccole modifiche:
- usa un logger invece dei print sparsi (cosi' la GUI puo' catturare i messaggi);
- resta l'UNICA parte che conosce l'HTML del sito FITP, isolata qui: se il sito
  cambia, si tocca solo questo file.
- legge anche la classifica federale (4.NC, 3.5, 2.8, ...).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from webdriver_manager.chrome import ChromeDriverManager

log = logging.getLogger(__name__)

_LOWER = "'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'"

# Classifica FITP: categoria 1-4, punto, gruppo a una cifra oppure "NC".
# I lookaround impediscono di pescare pezzi di numeri piu' lunghi
# (es. "3.5" dentro "jquery-3.5.1" o "12.3").
_RE_CLASSIFICA = re.compile(r"(?<![\w.])([1-4]\.(?:NC|[1-9]))(?![\w.])", re.IGNORECASE)

# Quanti caratteri di HTML guardare dopo ogni occorrenza di "classifica"
# nel fallback su page_source.
_FINESTRA_CLASSIFICA = 400


def _xpath_label(parola: str) -> str:
    """XPath case-insensitive per uno <span> che contiene `parola`."""
    return f"//span[contains(translate(text(),{_LOWER}),'{parola}')]"


class TesseraDriver:
    """Interroga il gestionale FITP per i dati di una tessera."""

    def __init__(self, headless: bool = True):
        options = Options()
        if headless:
            options.add_argument("--headless")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        self.driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()), options=options
        )
        self.driver.set_page_load_timeout(30)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def close(self):
        self.driver.quit()

    # --- helper interni -------------------------------------------------------
    def _wait_for_element(self, xpath: str, timeout: int = 8):
        return WebDriverWait(self.driver, timeout).until(
            EC.presence_of_element_located((By.XPATH, xpath))
        )

    def _apri(self, url: str, tentativi: int = 2) -> bool:
        """Carica la pagina una volta, con un retry se il caricamento fallisce."""
        for tentativo in range(tentativi):
            try:
                self.driver.get(url)
                return True
            except TimeoutException:
                if tentativo == tentativi - 1:
                    log.warning("Timeout nel caricamento della pagina: %s", url)
        return False

    def _valore_accanto(self, span):
        """Valore nel col-7 fratello dello <span> label (input o div)."""
        div_value = span.find_element(
            By.XPATH,
            "./ancestor::div[contains(@class, 'col-5')]"
            "/following-sibling::div[contains(@class, 'col-7')]",
        )
        for finder in (
            lambda: div_value.find_element(By.TAG_NAME, "input").get_attribute("value"),
            lambda: div_value.find_element(By.XPATH, ".//div").text,
        ):
            try:
                raw = (finder() or "").strip()
                if raw and raw != "-":
                    return raw
            except Exception:
                continue
        return None

    # --- lettori (operano sulla pagina GIA' caricata) -------------------------
    def _leggi_cittadinanza(self):
        try:
            span = self._wait_for_element(_xpath_label("cittadinanza"))
            return self._valore_accanto(span)
        except Exception:
            log.warning("Campo 'Cittadinanza' non trovato in pagina")
            return None

    def _leggi_certificato(self, data_inizio_str, data_fine_str, num_tessera=None):
        try:
            data_inizio = datetime.strptime(str(data_inizio_str), "%d/%m/%Y")
            data_fine = datetime.strptime(str(data_fine_str), "%d/%m/%Y")
        except ValueError as e:
            raise ValueError(f"Date torneo non valide ({data_inizio_str!r}, {data_fine_str!r}): "
                             f"servono nel formato gg/mm/aaaa") from e
        try:
            span = self._wait_for_element(_xpath_label("data scadenza certificato"))
            div_input = span.find_element(
                By.XPATH,
                "./ancestor::div[contains(@class, 'col-5')]"
                "/following-sibling::div[contains(@class, 'col-7')]",
            )
            data_str = (
                div_input.find_element(By.TAG_NAME, "input").get_attribute("value") or ""
            ).strip()
            data_certificato = datetime.strptime(data_str, "%d/%m/%Y")

            if data_certificato < data_inizio:
                return f"Scaduto il {data_str}"
            if data_certificato > data_fine:
                return "Valido"
            return f"In scadenza: {data_str}"
        except Exception:
            if num_tessera:
                log.warning("Tessera %s: nessuna data certificato trovata", num_tessera)
            return "N/D"

    def _leggi_classifica(self, num_tessera=None):
        """Classifica federale (es. '4.NC', '3.5') o None.

        1) Via DOM, come gli altri campi: label 'classifica' -> valore nel col-7.
        2) Fallback su page_source: regex cercata solo in una finestra limitata
           dopo ogni occorrenza di 'classifica', non su tutto l'HTML.
        """
        # 1) DOM (timeout corto: la pagina e' gia' caricata)
        try:
            span = self._wait_for_element(_xpath_label("classifica"), timeout=3)
            raw = self._valore_accanto(span)
            if raw:
                m = _RE_CLASSIFICA.search(raw)
                if m:
                    return m.group(1).upper()
        except Exception:
            pass

        # 2) Fallback regex su page_source
        try:
            html = self.driver.page_source
        except Exception:
            html = ""
        for label in re.finditer(r"classifica", html, re.IGNORECASE):
            inizio = label.end()
            m = _RE_CLASSIFICA.search(html, inizio, inizio + _FINESTRA_CLASSIFICA)
            if m:
                return m.group(1).upper()

        log.warning("Tessera %s: classifica non trovata", num_tessera or "?")
        return None

    # --- metodi principali ----------------------------------------------------
    def tessera_cs(
        self, url, data_cs, num_tessera=None
    ):
        """Carica la pagina UNA volta e restituisce
        (certificato, cittadinanza, vivaio, variato, classifica)."""
        if not self._apri(url):
            return "N/D", None, None, None, None
        medico = self._leggi_certificato(data_cs, data_cs, num_tessera)
        cittadinanza = self._leggi_cittadinanza()
        classifica = self._leggi_classifica(num_tessera)
        vivaio = self._leggi_vivaio(); variato = self._leggi_variato()
        return medico, cittadinanza, vivaio, variato, classifica

    def tessera_torneo(self, url, data_inizio_str, data_fine_str, num_tessera=None):
        """Carica la pagina UNA volta e restituisce (certificato, cittadinanza).

        Firma invariata per non rompere il codice esistente.
        """
        if not self._apri(url):
            return "N/D", None
        medico = self._leggi_certificato(data_inizio_str, data_fine_str, num_tessera)
        cittadinanza = self._leggi_cittadinanza()
        return medico, cittadinanza

    # --- wrapper retro-compatibili (ricaricano la pagina) ---------------------
    def certificato(self, url, data_inizio_str, data_fine_str, num_tessera=None):
        self._apri(url)
        return self._leggi_certificato(data_inizio_str, data_fine_str, num_tessera)

    def straniero(self, url):
        self._apri(url)
        return self._leggi_cittadinanza()

    def classifica(self, url):
        if not self._apri(url):
            return None
        return self._leggi_classifica()

    def _leggi_vivaio(self):
        try:
            span = self._wait_for_element(_xpath_label("vivaio"))
            return self._valore_accanto(span)
        except Exception:
            log.warning("Nessun campo 'VIVAIO' trovato")
            return None

    def _leggi_variato(self):
        try:
            span = self._wait_for_element(_xpath_label("trasferito"))
            value = self._valore_accanto(span)
        except Exception:
            log.warning("Nessun campo 'TRASFERITO' trovato")
            value = None
        return value if value in ("T", "N", "S") else None

    def vivaio(self, url):
        if not self._apri(url):
            return None
        return self._leggi_vivaio()

    def variato(self, url):
        if not self._apri(url):
            return None
        return self._leggi_variato()