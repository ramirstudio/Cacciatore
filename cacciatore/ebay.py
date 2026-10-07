"""Client minimale per la Browse API di eBay (ricerca pubblica, nessun login utente)."""
import base64
import logging
import time

import requests

log = logging.getLogger(__name__)

URL_TOKEN = "https://api.ebay.com/identity/v1/oauth2/token"
URL_RICERCA = "https://api.ebay.com/buy/browse/v1/item_summary/search"
SCOPE = "https://api.ebay.com/oauth/api_scope"


class ErroreEbay(Exception):
    pass


class Ebay:
    def __init__(self, client_id, client_secret):
        self.client_id = client_id
        self.client_secret = client_secret
        self._token = None
        self.chiamate = 0

    def _ottieni_token(self):
        credenziali = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        r = requests.post(
            URL_TOKEN,
            headers={
                "Authorization": f"Basic {credenziali}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "client_credentials", "scope": SCOPE},
            timeout=30,
        )
        if r.status_code != 200:
            raise ErroreEbay(f"Token eBay rifiutato ({r.status_code}): {r.text[:300]}")
        self._token = r.json()["access_token"]

    def cerca(self, q, marketplace, paese_venditore, consegna_in, categoria=None, limite=50):
        """Annunci più recenti per la query q, con sede del venditore nel paese indicato."""
        if not self._token:
            self._ottieni_token()
        filtri = [f"itemLocationCountry:{paese_venditore}"]
        if consegna_in:
            filtri.append(f"deliveryCountry:{consegna_in}")
        params = {"q": q, "sort": "newlyListed", "limit": limite, "filter": ",".join(filtri)}
        if categoria:
            params["category_ids"] = categoria
        headers = {
            "Authorization": f"Bearer {self._token}",
            "X-EBAY-C-MARKETPLACE-ID": marketplace,
            "Accept-Language": "en-US",
        }
        for tentativo in range(3):
            self.chiamate += 1
            r = requests.get(URL_RICERCA, params=params, headers=headers, timeout=30)
            if r.status_code == 200:
                return r.json().get("itemSummaries", [])
            if r.status_code == 401 and tentativo == 0:
                self._ottieni_token()
                headers["Authorization"] = f"Bearer {self._token}"
                continue
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(2 * (tentativo + 1))
                continue
            raise ErroreEbay(f"eBay {r.status_code} per {marketplace}/{paese_venditore}: {r.text[:300]}")
        raise ErroreEbay(f"eBay non risponde per {marketplace}/{paese_venditore}")


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def normalizza_annuncio(it, marketplace):
    """Riduce la risposta eBay ai campi che servono. Il nome del venditore NON viene salvato."""
    prezzo = it.get("price") or {}
    spedizioni = it.get("shippingOptions") or []
    sped_val, sped_val_cur = None, None
    for s in spedizioni:
        costo = s.get("shippingCost")
        if costo and _num(costo.get("value")) is not None:
            v = _num(costo["value"])
            if sped_val is None or v < sped_val:
                sped_val, sped_val_cur = v, costo.get("currency")
    venditore = it.get("seller") or {}
    luogo = it.get("itemLocation") or {}
    immagine = (it.get("image") or {}).get("imageUrl")
    if not immagine and it.get("thumbnailImages"):
        immagine = it["thumbnailImages"][0].get("imageUrl")
    opzioni = it.get("buyingOptions") or []
    return {
        "id": f"ebay:{it.get('itemId')}",
        "fonte": "eBay",
        "marketplace": marketplace,
        "titolo": it.get("title") or "",
        "url": it.get("itemWebUrl") or "",
        "immagine": immagine,
        "prezzo": _num(prezzo.get("value")),
        "valuta": prezzo.get("currency"),
        "spedizione": sped_val,
        "valuta_spedizione": sped_val_cur,
        "paese": luogo.get("country"),
        "condizione": it.get("condition"),
        "asta": "AUCTION" in opzioni and "FIXED_PRICE" not in opzioni,
        "fine_asta": it.get("itemEndDate"),
        "feedback_pct": _num(venditore.get("feedbackPercentage")),
        "feedback_n": int(venditore["feedbackScore"]) if venditore.get("feedbackScore") is not None else None,
        "pubblicato": it.get("itemCreationDate"),
    }
