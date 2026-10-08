"""Accesso alla rete con le buone maniere: legge robots.txt, aspetta tra una richiesta e l'altra,
dichiara chi è. Se un sito vieta un percorso, Cacciatore non lo scarica."""
import logging
import os
import time
from urllib.parse import urlencode, urlsplit
from urllib.robotparser import RobotFileParser

import requests

log = logging.getLogger(__name__)

AGENTE = "CacciatoreBot/1.0 (consultazione personale, rispetta robots.txt)"


class Vietato(Exception):
    """robots.txt del sito non permette di leggere questo indirizzo."""


class ErroreRete(Exception):
    pass


class Rete:
    def __init__(self, pausa=2.0, timeout=45, max_byte=15_000_000, sessione=None):
        self.pausa = pausa
        self.timeout = timeout
        self.max_byte = max_byte
        self.richieste = 0
        self.s = sessione or requests.Session()
        contatto = os.environ.get("CACCIATORE_CONTATTO", "").strip()
        agente = AGENTE + (f" contatto: {contatto}" if contatto else "")
        self.s.headers.update({"User-Agent": agente, "Accept-Language": "en,it;q=0.8"})
        self._robots = {}
        self.motivo_robots = {}
        self._ultimo = {}
        self.pausa_host = {}  # pausa più lunga per i siti che la chiedono (Crawl-delay)

    @staticmethod
    def _base(url):
        u = urlsplit(url)
        return f"{u.scheme}://{u.netloc}"

    def _pausa(self, base):
        passato = time.monotonic() - self._ultimo.get(base, -1e9)
        pausa = max(self.pausa, self.pausa_host.get(base, 0))
        if passato < pausa:
            time.sleep(pausa - passato)
        self._ultimo[base] = time.monotonic()

    def _regole(self, base):
        if base in self._robots:
            return self._robots[base]
        rp = RobotFileParser()
        try:
            self._pausa(base)
            r = self.s.get(base + "/robots.txt", timeout=self.timeout)
            if r.status_code in (401, 403):
                rp.disallow_all = True
                self.motivo_robots[base] = f"il sito risponde {r.status_code} anche a robots.txt: blocca i programmi automatici"
            elif r.status_code >= 400:
                rp.allow_all = True
            else:
                rp.parse(r.text.splitlines())
        except requests.RequestException as e:
            log.warning("robots.txt di %s non raggiungibile (%s): non insisto.", base, e)
            self.motivo_robots[base] = f"non raggiungibile da qui ({str(e)[:90]})"
            rp.disallow_all = True
        rp.modified()
        self._robots[base] = rp
        return rp

    def permesso(self, url):
        u = urlsplit(url)
        percorso = u.path + (("?" + u.query) if u.query else "")
        return self._regole(self._base(url)).can_fetch(AGENTE, percorso or "/")

    def get(self, url, params=None, intestazioni=None, robots=True):
        """robots=False solo per le API ufficiali usate con la propria chiave: lì vale il contratto dell'API."""
        if params:
            sep = "&" if "?" in url else "?"
            url = url + sep + urlencode(params)
        if robots and not self.permesso(url):
            raise Vietato(f"robots.txt vieta {url}")
        base = self._base(url)
        for tentativo in range(2):
            self._pausa(base)
            self.richieste += 1
            try:
                r = self.s.get(url, timeout=self.timeout, headers=intestazioni)
            except requests.RequestException as e:
                if tentativo == 0:  # un solo nuovo tentativo per timeout e cadute di connessione
                    time.sleep(3)
                    continue
                raise ErroreRete(f"{url}: {e}") from e
            if r.status_code in (429, 503) and tentativo == 0:
                try:
                    attesa = min(30, int(r.headers.get("Retry-After", "5")))
                except ValueError:
                    attesa = 5
                time.sleep(attesa)
                continue
            if r.status_code >= 400:
                raise ErroreRete(f"{url}: risposta {r.status_code}")
            if len(r.content) > self.max_byte:
                raise ErroreRete(f"{url}: risposta troppo grande")
            return r
        raise ErroreRete(f"{url}: il sito chiede di rallentare")
