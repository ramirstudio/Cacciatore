"""Lettura di negozi e siti di usato, senza login e senza aggirare protezioni.

Ogni sito si descrive in config.yaml sotto "fonti" con un tipo di lettura:
  shopify      elenco prodotti pubblico dei negozi Shopify (/products.json)
  woocommerce  API pubblica dei negozi WooCommerce (/wp-json/wc/store/v1/products)
  jsonld       pagine di elenco con dati strutturati schema.org (Product o ItemList)
  rss          feed RSS o Atom, per forum e bacheche di annunci
  html         pagine di elenco lette con selettori CSS scritti da te

Prima di ogni richiesta Rete controlla robots.txt: se il sito non vuole, non si scarica nulla.
"""
import json
import logging
import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin

log = logging.getLogger(__name__)

SEGNI_VALUTA = [
    ("€", "EUR"), ("eur", "EUR"), ("£", "GBP"), ("gbp", "GBP"), ("$", "USD"), ("usd", "USD"),
    ("zł", "PLN"), ("zl", "PLN"), ("pln", "PLN"), ("kč", "CZK"), ("czk", "CZK"), ("huf", "HUF"),
    ("ft", "HUF"), ("ron", "RON"), ("lei", "RON"), ("лв", "BGN"), ("bgn", "BGN"), ("¥", "JPY"),
    ("円", "JPY"), ("jpy", "JPY"), ("hkd", "HKD"), ("cny", "CNY"),
]
USATO = re.compile(
    r"\b(used|second[\s-]?hand|pre[\s-]?owned|gebraucht|usato|occasion|d'occasion|refurb\w*|"
    r"ex[\s-]?demo|vintage|używan\w*|použit\w*|second main)\b", re.I)
NUOVO = re.compile(r"^\s*(new|brand new|nuovo|neu|nowy|nový)\b", re.I)


def slug(testo):
    return re.sub(r"[^a-z0-9]+", "-", testo.lower()).strip("-")


def https(url, base=None):
    if not url:
        return None
    if url.startswith("//"):
        url = "https:" + url
    if base:
        url = urljoin(base + "/", url)
    return url if url.startswith("https://") else None


def parse_prezzo(testo):
    """Primo numero di un testo come valore decimale. Gestisce 1.234,56 e 1,234.56 e 1 299 zł."""
    if testo is None:
        return None
    if isinstance(testo, (int, float)):
        return float(testo)
    m = re.search(r"\d[\d.,\s  ]*", str(testo))
    if not m:
        return None
    n = re.sub(r"[\s  ]", "", m.group(0)).rstrip(".,")
    if "," in n and "." in n:
        dec = "," if n.rfind(",") > n.rfind(".") else "."
        mig = "." if dec == "," else ","
        n = n.replace(mig, "").replace(dec, ".")
    elif "," in n:
        n = n.replace(",", ".") if re.search(r",\d{1,2}$", n) and n.count(",") == 1 else n.replace(",", "")
    elif "." in n:
        if n.count(".") > 1 or re.search(r"\.\d{3}$", n):
            n = n.replace(".", "")
    try:
        return float(n)
    except ValueError:
        return None


def valuta_da_testo(testo, predefinita):
    t = (testo or "").lower()
    for segno, codice in SEGNI_VALUTA:
        if segno in t:
            return codice
    return predefinita


def _voce(fonte, ident, titolo, url, prezzo, valuta, immagine=None, condizione=None, nuovo=False,
          pubblicato=None, asta=False):
    return {
        "id": f"{slug(fonte['nome'])}:{ident}",
        "fonte": fonte["nome"],
        "marketplace": "NEGOZIO",
        "tipo_fonte": "negozio",
        "titolo": (titolo or "").strip(),
        "url": url,
        "immagine": immagine,
        "prezzo": prezzo,
        "valuta": valuta,
        "spedizione": None,
        "valuta_spedizione": None,
        "paese": fonte.get("paese"),
        "condizione": condizione,
        "asta": asta,
        "fine_asta": None,
        "feedback_pct": None,
        "feedback_n": None,
        "pubblicato": pubblicato,
        "nuovo": nuovo,
    }


# ---------------------------------------------------------------- Shopify
def leggi_shopify(fonte, rete):
    base = fonte["url"].rstrip("/")
    collezioni = fonte.get("collezioni") or [None]
    per_pagina = 100
    voci, completo = {}, True
    for coll in collezioni:
        percorso = f"/collections/{coll}/products.json" if coll else "/products.json"
        for pagina in range(1, int(fonte.get("max_pagine", 10)) + 1):
            r = rete.get(base + percorso, params={"limit": per_pagina, "page": pagina})
            try:
                prodotti = r.json().get("products", [])
            except ValueError as e:
                raise ValueError(f"{base}{percorso}: la risposta non è JSON ({e})") from e
            for p in prodotti:
                v = _da_shopify(fonte, base, p)
                if v:
                    voci[v["id"]] = v
            if len(prodotti) < per_pagina:
                break
        else:
            completo = False  # raggiunto il limite di pagine: l'elenco potrebbe essere parziale
    return list(voci.values()), completo


def _da_shopify(fonte, base, p):
    disponibili = [v for v in p.get("variants", []) if v.get("available")]
    if not disponibili:
        return None
    prezzi = [parse_prezzo(v.get("price")) for v in disponibili]
    prezzi = [x for x in prezzi if x is not None]
    if not prezzi or not p.get("handle"):
        return None
    titoli_var = [str(v.get("title") or "") for v in disponibili] + [str(v.get("option1") or "") for v in disponibili]
    testo_stato = " ".join(titoli_var + [str(p.get("product_type") or "")] + [str(t) for t in p.get("tags", [])])
    usato = bool(USATO.search(testo_stato)) or bool(USATO.search(p.get("title") or ""))
    nuovo = (not usato) and any(NUOVO.match(t) for t in titoli_var)
    immagini = p.get("images") or []
    immagine = https(immagini[0].get("src")) if immagini else None
    return _voce(
        fonte, p["handle"], p.get("title"), f"{base}/products/{p['handle']}", min(prezzi), fonte.get("valuta", "EUR"),
        immagine=immagine, condizione="Used" if usato else ("New" if nuovo else None), nuovo=nuovo,
        pubblicato=p.get("published_at"),
    )


# ------------------------------------------------------------ WooCommerce
def leggi_woocommerce(fonte, rete):
    base = fonte["url"].rstrip("/")
    voci, completo = {}, True
    per_pagina = 100
    for pagina in range(1, int(fonte.get("max_pagine", 10)) + 1):
        r = rete.get(base + "/wp-json/wc/store/v1/products",
                     params={"per_page": per_pagina, "page": pagina, "orderby": "date", "order": "desc"})
        prodotti = r.json()
        if not isinstance(prodotti, list):
            raise ValueError(f"{base}: la risposta WooCommerce non è un elenco")
        for p in prodotti:
            if not p.get("is_in_stock", True):
                continue
            pr = p.get("prices") or {}
            decimali = int(pr.get("currency_minor_unit", 2))
            valore = parse_prezzo(pr.get("price"))
            if valore is None or not p.get("permalink"):
                continue
            valore = valore / (10 ** decimali)
            nomi = " ".join([c.get("name", "") for c in p.get("categories", [])] +
                            [t.get("name", "") for t in p.get("tags", [])] + [p.get("name", "")])
            usato = bool(USATO.search(nomi))
            imgs = p.get("images") or []
            voci[str(p["id"])] = _voce(
                fonte, p["id"], re.sub(r"&amp;", "&", p.get("name", "")), p["permalink"], valore,
                pr.get("currency_code") or fonte.get("valuta", "EUR"),
                immagine=https(imgs[0].get("src")) if imgs else None,
                condizione="Used" if usato else None,
            )
        if len(prodotti) < per_pagina:
            break
    else:
        completo = False
    return list(voci.values()), completo


# ---------------------------------------------------------------- JSON-LD
def _tipi(nodo):
    t = nodo.get("@type")
    return [t] if isinstance(t, str) else list(t or [])


def _nodi(dato):
    if isinstance(dato, list):
        for x in dato:
            yield from _nodi(x)
    elif isinstance(dato, dict):
        yield dato
        for chiave in ("@graph", "itemListElement", "item", "mainEntity"):
            if chiave in dato:
                yield from _nodi(dato[chiave])


def leggi_jsonld(fonte, rete):
    from bs4 import BeautifulSoup
    voci, completo = {}, True
    for indirizzo in fonte["urls"]:
        r = rete.get(indirizzo)
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
            try:
                dato = json.loads(tag.string or tag.get_text() or "null")
            except ValueError:
                continue
            for n in _nodi(dato):
                if "Product" not in _tipi(n):
                    continue
                offerta = n.get("offers") or {}
                if isinstance(offerta, list):
                    offerta = offerta[0] if offerta else {}
                if "outofstock" in str(offerta.get("availability", "")).lower() or \
                        "soldout" in str(offerta.get("availability", "")).lower():
                    continue
                prezzo = parse_prezzo(offerta.get("price") or offerta.get("lowPrice"))
                url = https(n.get("url") or offerta.get("url"), fonte["url"].rstrip("/"))
                if prezzo is None or not url:
                    continue
                img = n.get("image")
                if isinstance(img, list):
                    img = img[0] if img else None
                if isinstance(img, dict):
                    img = img.get("url")
                titolo = n.get("name") or ""
                usato = bool(USATO.search(titolo + " " + str(offerta.get("itemCondition", ""))))
                voci[url] = _voce(fonte, slug(url.split("//", 1)[-1])[:80], titolo, url, prezzo,
                                  offerta.get("priceCurrency") or fonte.get("valuta", "EUR"),
                                  immagine=https(img, fonte["url"].rstrip("/")),
                                  condizione="Used" if usato else None)
    return list(voci.values()), completo


# -------------------------------------------------------------------- RSS
def _nome_locale(tag):
    return tag.rsplit("}", 1)[-1]


def leggi_rss(fonte, rete):
    voci = {}
    for indirizzo in fonte["urls"]:
        r = rete.get(indirizzo)
        radice = ET.fromstring(r.content)
        for el in radice.iter():
            if _nome_locale(el.tag) not in ("item", "entry"):
                continue
            campi = {}
            immagine = None
            for f in el:
                nome = _nome_locale(f.tag)
                if nome in ("enclosure", "thumbnail", "content") and (f.get("url") or "").startswith("http"):
                    immagine = immagine or f.get("url")
                elif nome == "link":
                    campi["link"] = f.get("href") or (f.text or "").strip()
                elif nome in ("title", "description", "summary", "content", "guid", "pubDate", "published", "updated"):
                    campi[nome] = (f.text or "").strip()
            testo = f"{campi.get('title', '')} {campi.get('description', campi.get('summary', ''))}"
            testo_pulito = re.sub(r"<[^>]+>", " ", testo)
            prezzo = None
            m = re.search(r"(?:[€£$]\s?\d[\d.,\s]*|\d[\d.,\s]*\s?(?:€|eur|£|gbp|\$|usd|zł|pln|kč|czk|ft|huf|lei|ron|лв|bgn))",
                          testo_pulito, re.I)
            if m:
                prezzo = parse_prezzo(m.group(0))
            url = https(campi.get("link"))
            if not url or prezzo is None:
                continue
            valuta = valuta_da_testo(m.group(0), fonte.get("valuta", "EUR"))
            voci[url] = _voce(fonte, slug(campi.get("guid") or url.split("//", 1)[-1])[:80], campi.get("title"),
                              url, prezzo, valuta, immagine=https(immagine),
                              pubblicato=campi.get("pubDate") or campi.get("published"))
    return list(voci.values()), True


# ------------------------------------------------------------------- HTML
def leggi_html(fonte, rete):
    from bs4 import BeautifulSoup
    sel = fonte["selettori"]
    base = fonte["url"].rstrip("/")
    voci = {}
    for indirizzo in fonte["urls"]:
        r = rete.get(indirizzo)
        soup = BeautifulSoup(r.text, "html.parser")
        for blocco in soup.select(sel["voce"]):
            t = blocco.select_one(sel["titolo"])
            a = blocco.select_one(sel.get("link", sel["titolo"]))
            p = blocco.select_one(sel["prezzo"])
            if not (t and a and p):
                continue
            url = https(a.get("href") if a.name == "a" else (a.find("a") or {}).get("href"), base)
            testo_prezzo = p.get_text(" ", strip=True)
            prezzo = parse_prezzo(testo_prezzo)
            if not url or prezzo is None:
                continue
            im = blocco.select_one(sel["immagine"]) if sel.get("immagine") else None
            src = None
            if im is not None:
                src = im.get("src") or im.get("data-src")
            voci[url] = _voce(fonte, slug(url.split("//", 1)[-1])[:80], t.get_text(" ", strip=True), url, prezzo,
                              valuta_da_testo(testo_prezzo, fonte.get("valuta", "EUR")),
                              immagine=https(src, base))
    return list(voci.values()), True


LETTORI = {
    "shopify": leggi_shopify,
    "woocommerce": leggi_woocommerce,
    "jsonld": leggi_jsonld,
    "rss": leggi_rss,
    "html": leggi_html,
}


def scarica(fonte, rete):
    """Restituisce (voci, completo). Se completo è vero, gli annunci della fonte non più presenti sono venduti."""
    lettore = LETTORI.get(fonte.get("tipo"))
    if not lettore:
        raise ValueError(f"tipo di fonte sconosciuto: {fonte.get('tipo')!r}")
    return lettore(fonte, rete)
