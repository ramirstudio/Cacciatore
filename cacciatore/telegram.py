"""Notifiche Telegram."""
import html
import logging

import requests

log = logging.getLogger(__name__)


class Telegram:
    def __init__(self, token, chat_id):
        self.base = f"https://api.telegram.org/bot{token}"
        self.chat_id = chat_id

    def _post(self, metodo, **dati):
        r = requests.post(f"{self.base}/{metodo}", data=dati, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"Telegram {metodo} {r.status_code}: {r.text[:200]}")

    def testo(self, messaggio):
        self._post("sendMessage", chat_id=self.chat_id, text=messaggio[:4000],
                   parse_mode="HTML", disable_web_page_preview="true")

    def annuncio(self, testo, foto=None):
        if foto:
            try:
                self._post("sendPhoto", chat_id=self.chat_id, photo=foto,
                           caption=testo[:1000], parse_mode="HTML")
                return
            except Exception as e:  # noqa: BLE001
                log.warning("Foto rifiutata da Telegram, invio solo testo: %s", e)
        self.testo(testo)


def euro(x):
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " EUR"


def formatta_avviso(a, nomi_paesi):
    e = html.escape
    righe = [f"<b>{e(a['titolo'][:150])}</b>"]
    if a.get("motivi_avviso"):
        righe.append(e(" · ".join(a["motivi_avviso"])))
    prezzo = euro(a["prezzo_eur"]) if a.get("prezzo_eur") is not None else "prezzo non disponibile"
    if a.get("asta"):
        prezzo += " (asta, offerta attuale)"
    riga_prezzo = f"Prezzo {prezzo}"
    if a.get("spedizione_eur") is not None:
        riga_prezzo += f" + spedizione {euro(a['spedizione_eur'])}"
    righe.append(riga_prezzo)
    if a.get("extra_ue"):
        righe.append(f"Stima arrivato a casa (IVA e dogana incluse): {euro(a['totale_eur'])}")
    else:
        righe.append(f"Totale stimato: {euro(a['totale_eur'])}")
    venditore = nomi_paesi.get(a.get("paese"), a.get("paese") or "paese non indicato")
    if a.get("tipo_fonte") == "negozio":
        venditore = f"Negozio {a['fonte']}, {venditore}"
    elif a.get("feedback_pct") is not None:
        venditore += f" · venditore {a['feedback_pct']:.1f}% su {a.get('feedback_n', 0)} feedback"
    righe.append(e(venditore))
    if a.get("avvisi"):
        righe.append("Attenzione: " + e("; ".join(a["avvisi"])))
    righe.append(a["url"])
    return "\n".join(righe)
