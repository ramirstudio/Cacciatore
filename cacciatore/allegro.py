"""Ricerca opzionale su Allegro (Polonia). Funziona solo con un'app verificata da Allegro."""
import base64
import logging

import requests

log = logging.getLogger(__name__)

URL_TOKEN = "https://allegro.pl/auth/oauth/token"
URL_LISTING = "https://api.allegro.pl/offers/listing"
ACCEPT = "application/vnd.allegro.public.v1+json"


class AllegroNonAbilitato(Exception):
    pass


class Allegro:
    def __init__(self, client_id, client_secret):
        self.client_id = client_id
        self.client_secret = client_secret
        self._token = None

    def _ottieni_token(self):
        cred = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        r = requests.post(
            URL_TOKEN,
            params={"grant_type": "client_credentials"},
            headers={"Authorization": f"Basic {cred}"},
            timeout=30,
        )
        r.raise_for_status()
        self._token = r.json()["access_token"]

    def cerca(self, frase, limite=50):
        if not self._token:
            self._ottieni_token()
        r = requests.get(
            URL_LISTING,
            params={"phrase": frase, "sort": "-startTime", "limit": limite},
            headers={"Authorization": f"Bearer {self._token}", "Accept": ACCEPT},
            timeout=30,
        )
        if r.status_code == 403:
            raise AllegroNonAbilitato(
                "Allegro ha risposto 403: l'app non è ancora verificata per la ricerca pubblica."
            )
        r.raise_for_status()
        voci = r.json().get("items", {})
        return (voci.get("regular") or []) + (voci.get("promoted") or [])


def normalizza_annuncio(it):
    prezzo = ((it.get("sellingMode") or {}).get("price")) or {}
    consegna = ((it.get("delivery") or {}).get("lowestPrice")) or {}
    immagini = it.get("images") or []
    return {
        "id": f"allegro:{it.get('id')}",
        "fonte": "Allegro",
        "marketplace": "ALLEGRO",
        "titolo": it.get("name") or "",
        "url": f"https://allegro.pl/oferta/{it.get('id')}",
        "immagine": immagini[0].get("url") if immagini else None,
        "prezzo": float(prezzo["amount"]) if prezzo.get("amount") else None,
        "valuta": prezzo.get("currency"),
        "spedizione": float(consegna["amount"]) if consegna.get("amount") else None,
        "valuta_spedizione": consegna.get("currency"),
        "paese": "PL",
        "condizione": None,
        "asta": ((it.get("sellingMode") or {}).get("format")) == "AUCTION",
        "fine_asta": None,
        "feedback_pct": None,
        "feedback_n": None,
        "pubblicato": None,
    }
