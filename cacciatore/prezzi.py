"""Conversione valute e stima del prezzo arrivato a casa."""
import logging

import requests

log = logging.getLogger(__name__)

PAESI_UE = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU",
    "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE",
}

# Tassi di ripiego, usati solo se il servizio dei cambi non risponde.
# Unità di valuta per 1 euro. Valori approssimativi.
TASSI_RIPIEGO = {
    "EUR": 1.0, "USD": 1.15, "GBP": 0.86, "JPY": 170.0, "CNY": 8.2, "HKD": 9.0,
    "PLN": 4.25, "CZK": 24.5, "HUF": 395.0, "RON": 5.1, "SEK": 11.0, "DKK": 7.46, "BGN": 1.96,
}


def scarica_tassi():
    """Tassi BCE dal servizio gratuito Frankfurter. Restituisce unità per 1 EUR."""
    for url in ("https://api.frankfurter.dev/v1/latest", "https://api.frankfurter.app/latest"):
        try:
            r = requests.get(url, params={"base": "EUR"}, timeout=20)
            r.raise_for_status()
            tassi = dict(r.json()["rates"])
            tassi["EUR"] = 1.0
            return tassi
        except Exception as e:  # noqa: BLE001
            log.warning("Cambi non disponibili da %s: %s", url, e)
    log.warning("Uso i tassi di ripiego, i prezzi in euro saranno approssimati.")
    return dict(TASSI_RIPIEGO)


def in_euro(valore, valuta, tassi):
    if valore is None:
        return None
    tasso = tassi.get(valuta) or TASSI_RIPIEGO.get(valuta)
    if not tasso:
        return None
    return round(float(valore) / tasso, 2)


def arrivo_a_casa(prezzo_eur, spedizione_eur, paese, cfg):
    """Stima del costo finale in Italia.

    Dentro l'UE il totale è prezzo più spedizione. Fuori UE si aggiungono IVA,
    un costo fisso di sdoganamento oltre la soglia e un eventuale dazio.
    Restituisce (totale, extra_ue).
    """
    base = (prezzo_eur or 0) + (spedizione_eur or 0)
    if paese in PAESI_UE:
        return round(base, 2), False
    iva = base * cfg.get("iva_importazione", 0.22)
    soglia = cfg.get("soglia_sdoganamento_eur", 150)
    fisso = cfg.get("costo_sdoganamento_eur", 12) if base > soglia else 0
    dazio = base * cfg.get("dazio", 0.0)
    return round(base + iva + fisso + dazio, 2), True
