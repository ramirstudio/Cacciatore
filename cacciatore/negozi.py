"""Lettura di negozi e siti di usato, senza login e senza aggirare protezioni.

Ogni sito si descrive in config.yaml sotto "fonti" con un tipo di lettura:
  shopify      elenco prodotti pubblico dei negozi Shopify (/products.json)
  woocommerce  API pubblica dei negozi WooCommerce (/wp-json/wc/store/v1/products)
  jsonld       pagine di elenco con dati strutturati schema.org (Product o ItemList)
  rss          feed RSS o Atom, per forum e bacheche di annunci
  html         pagine di elenco lette con selettori CSS scritti da te
  etsy         API ufficiale di Etsy, con la tua chiave personale
  email        le mail di "ricerca salvata" che Subito, Vinted ecc. mandano a te

Prima di ogni richiesta Rete controlla robots.txt: se il sito non vuole, non si scarica nulla.
"""
import email as modulo_email
import email.policy
import hashlib
import html
import imaplib
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
import xml.etree.ElementTree as ET
from urllib.parse import urljoin

from .rete import ErroreRete

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
            try:
                r = rete.get(base + percorso, params={"limit": per_pagina, "page": pagina})
            except ErroreRete:
                if pagina == 1 and not voci:
                    raise
                completo = False  # pagine successive non raggiunte: tengo quelle già lette
                break
            try:
                prodotti = r.json().get("products", [])
            except ValueError as e:
                raise ValueError(f"{base}{percorso}: la risposta non è JSON ({e})") from e
            for p in prodotti:
                v = _da_shopify(fonte, base, p)
                if v and fonte.get("solo_usato") and v["condizione"] != "Used":
                    continue
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
    per_pagina = int(fonte.get("per_pagina", 40))  # pagine piccole: i server WordPress lenti vanno in timeout con 100
    for pagina in range(1, int(fonte.get("max_pagine", 15)) + 1):
        parametri = {"per_page": per_pagina, "page": pagina, "orderby": "date", "order": "desc"}
        if fonte.get("categoria"):
            parametri["category"] = fonte["categoria"]
        try:
            r = rete.get(base + "/wp-json/wc/store/v1/products", params=parametri)
        except ErroreRete:
            if pagina == 1:
                raise
            completo = False
            break
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
                fonte, p["id"], html.unescape(p.get("name", "")), p["permalink"], valore,
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


# ------------------------------------------------------------------- Etsy
ETSY_API = "https://openapi.etsy.com/v3/application/listings/active"


def _paese_etsy(annuncio):
    """Paese di spedizione del venditore, se l'API lo fornisce (profilo di spedizione o negozio)."""
    for nodo in (annuncio.get("shipping_profile"), annuncio.get("shop"), annuncio):
        if isinstance(nodo, dict):
            for chiave in ("origin_country_iso", "ships_from_country_iso", "country_iso"):
                v = nodo.get(chiave)
                if isinstance(v, str) and len(v) == 2:
                    return v.upper()
    return None


def _prezzo_etsy(p):
    if isinstance(p, dict):
        try:
            return float(p["amount"]) / float(p.get("divisor") or 100), p.get("currency_code")
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            return None, None
    return parse_prezzo(p), None


def leggi_etsy(fonte, rete):
    """Cerca per parole chiave con l'API ufficiale v3. Serve una chiave personale di Etsy."""
    chiave = os.environ.get("ETSY_API_KEY", "").strip()
    segreto = os.environ.get("ETSY_API_SECRET", "").strip()
    if not chiave:
        raise ErroreRete("mancano i secret ETSY_API_KEY (e ETSY_API_SECRET): crea la chiave su etsy.com/developers")
    intestazioni = {"x-api-key": f"{chiave}:{segreto}" if segreto else chiave}
    per_pagina = 100
    voci, letti, senza_paese = {}, 0, 0
    scarta_ignoti = fonte.get("paese_ignoto", "scarta") == "scarta"
    for frase in fonte["parole"]:
        for pagina in range(int(fonte.get("max_pagine", 1))):
            parametri = {"keywords": frase, "limit": per_pagina, "offset": pagina * per_pagina,
                         "sort_on": "created", "sort_order": "desc", "includes": "Images,Shipping"}
            try:
                dati = rete.get(ETSY_API, parametri, intestazioni=intestazioni, robots=False).json()
            except ErroreRete as e:
                if "401" in str(e) or "403" in str(e):
                    raise ErroreRete("Etsy rifiuta la chiave (errata, o ancora in attesa di approvazione)") from e
                if not voci and letti == 0:
                    raise
                log.warning("Etsy, ricerca «%s» pagina %d non letta: %s", frase, pagina + 1, e)
                break
            risultati = dati.get("results") or []
            letti += len(risultati)
            for r in risultati:
                if r.get("state") not in (None, "active"):
                    continue
                url = (r.get("url") or "").split("?")[0]
                prezzo, valuta = _prezzo_etsy(r.get("price"))
                if not https(url) or prezzo is None or not r.get("listing_id"):
                    continue
                paese = _paese_etsy(r) or fonte.get("paese")
                if paese is None and scarta_ignoti:
                    senza_paese += 1
                    continue
                immagini = r.get("images") or []
                im = (immagini[0].get("url_570xN") or immagini[0].get("url_fullxfull")) if immagini else None
                ts = r.get("original_creation_timestamp") or r.get("creation_timestamp")
                pubblicato = None
                if isinstance(ts, (int, float)):
                    pubblicato = datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                v = _voce(fonte, str(r["listing_id"]), r.get("title"), url, prezzo,
                          valuta or fonte.get("valuta", "EUR"), immagine=https(im), pubblicato=pubblicato)
                v["paese"] = paese
                voci[v["id"]] = v
            if len(risultati) < per_pagina:
                break
    if letti and not voci and senza_paese:
        raise ErroreRete("Etsy non indica il paese del venditore: scartati tutti gli annunci. "
                         "Se vuoi vederli lo stesso, metti paese_ignoto: tieni nella fonte")
    if senza_paese:
        log.warning("Etsy: %d annunci scartati perché il paese del venditore non è indicato.", senza_paese)
    return list(voci.values()), False  # una ricerca per parole non è un catalogo: niente rimozione dei venduti


# ------------------------------------------------------------- Email (IMAP)
PREZZO_TESTO = re.compile(r"(?:€|eur)\s?\d[\d.,]*|\d[\d.,]*\s?(?:€|eur)", re.I)
LINK_DA_SALTARE = re.compile(r"unsubscribe|disiscri|preferenz|privacy|cookie|mailto:|/help|assistenza|termini|facebook|instagram|apple\.com|google\.com/store", re.I)
TLD_PAESI = {"it": "IT", "fr": "FR", "de": "DE", "es": "ES", "pl": "PL", "cz": "CZ", "lt": "LT", "nl": "NL",
             "be": "BE", "at": "AT", "pt": "PT", "sk": "SK", "hu": "HU", "ro": "RO", "hr": "HR", "gr": "GR",
             "se": "SE", "dk": "DK", "fi": "FI", "uk": "GB"}


def _paese_da_dominio(url):
    host = re.sub(r"^https?://", "", url).split("/")[0].lower()
    if host.endswith(".co.uk"):
        return "GB"
    return TLD_PAESI.get(host.rsplit(".", 1)[-1])


def estrai_da_html(html, fonte):
    """Trova gli annunci in una mail: ogni link all'annuncio con titolo, prezzo e foto nello stesso blocco."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    filtro = re.compile(fonte["link"]) if fonte.get("link") else None
    trovati = {}
    for a in soup.find_all("a", href=True):
        url = a["href"].strip()
        if not url.startswith("https://") or LINK_DA_SALTARE.search(url):
            continue
        if filtro and not filtro.search(url):
            continue
        blocco = a
        for _ in range(7):
            if PREZZO_TESTO.search(blocco.get_text(" ", strip=True)):
                break
            if blocco.parent is None:
                break
            blocco = blocco.parent
        testo_blocco = blocco.get_text(" ", strip=True)
        m = PREZZO_TESTO.search(testo_blocco)
        if not m:
            continue
        # un blocco con più annunci diversi non è affidabile per questo link: si resta al link stesso
        titolo = a.get_text(" ", strip=True)
        if not titolo or PREZZO_TESTO.fullmatch(titolo):
            img_alt = (a.find("img") or {}).get("alt") if a.find("img") else None
            titolo = img_alt or ""
        if not titolo:
            righe = [t.strip() for t in blocco.stripped_strings if not PREZZO_TESTO.search(t) and len(t.strip()) > 3]
            titolo = righe[0] if righe else ""
        if len(titolo) < 4:
            continue
        immagine = None
        for im in blocco.find_all("img"):
            src = im.get("src") or im.get("data-src") or ""
            try:
                piccola = int(im.get("width") or 100) <= 5 or int(im.get("height") or 100) <= 5
            except ValueError:
                piccola = False
            if src.startswith("https://") and not piccola and not re.search(r"pixel|track|open\.|logo|icon", src, re.I):
                immagine = src
                break
        chiave = url.split("?")[0] if len(url.split("?")[0].split("//", 1)[-1]) > 20 else url
        if chiave in trovati:
            continue
        trovati[chiave] = {"url": url.split("#")[0], "titolo": titolo, "prezzo": parse_prezzo(m.group(0)),
                           "valuta": valuta_da_testo(m.group(0), fonte.get("valuta", "EUR")), "immagine": immagine}
    return list(trovati.values())


def leggi_email(fonte, rete):
    """Legge, in sola lettura, le mail di ricerca salvata arrivate negli ultimi giorni.

    Nessun accesso ai siti: Cacciatore vede solo ciò che i siti mandano a te per mail.
    """
    utente = os.environ.get("EMAIL_IMAP_UTENTE", "").strip()
    password = os.environ.get("EMAIL_IMAP_PASSWORD", "").strip()
    if not utente or not password:
        raise ErroreRete("mancano i secret EMAIL_IMAP_UTENTE ed EMAIL_IMAP_PASSWORD")
    giorni = int(fonte.get("giorni", 3))
    dal = (datetime.now(timezone.utc) - timedelta(days=giorni)).strftime("%d-%b-%Y")
    voci = {}
    try:
        casella = imaplib.IMAP4_SSL(fonte.get("server", "imap.gmail.com"), timeout=30)
        try:
            casella.login(utente, password)
            casella.select(fonte.get("cartella", "INBOX"), readonly=True)  # sola lettura: non tocca le mail
            numeri = set()
            for mittente in fonte["mittenti"]:
                stato, risposta = casella.search(None, "SINCE", dal, "FROM", f'"{mittente}"')
                if stato == "OK" and risposta and risposta[0]:
                    numeri.update(risposta[0].split())
            for n in sorted(numeri, key=int)[-int(fonte.get("max_mail", 60)):]:
                stato, parti = casella.fetch(n, "(BODY.PEEK[])")
                if stato != "OK" or not parti or not isinstance(parti[0], tuple):
                    continue
                msg = modulo_email.message_from_bytes(parti[0][1], policy=modulo_email.policy.default)
                corpo = msg.get_body(preferencelist=("html",))
                if corpo is None:
                    continue
                data = None
                try:
                    data = msg["date"].datetime.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                except Exception:  # noqa: BLE001
                    pass
                for e in estrai_da_html(corpo.get_content(), fonte):
                    ident = hashlib.sha1(e["url"].split("?")[0].encode()).hexdigest()[:16]
                    v = _voce(fonte, ident, e["titolo"], e["url"], e["prezzo"], e["valuta"],
                              immagine=e["immagine"], pubblicato=data)
                    if fonte.get("paese_da_dominio"):
                        v["paese"] = _paese_da_dominio(e["url"]) or fonte.get("paese")
                    voci[v["id"]] = v
        finally:
            try:
                casella.logout()
            except Exception:  # noqa: BLE001
                pass
    except imaplib.IMAP4.error as e:
        raise ErroreRete(f"accesso alla posta rifiutato ({e}): controlla utente e password per app") from e
    except OSError as e:
        raise ErroreRete(f"posta non raggiungibile: {e}") from e
    return list(voci.values()), False


# -------------------------------------------------------------------- MPB
def leggi_mpb(fonte, rete):
    """Pagine di categoria di MPB (usato garantito): un elemento per modello, con il prezzo più basso disponibile."""
    from bs4 import BeautifulSoup
    base = fonte["url"].rstrip("/")
    voci = {}
    for indirizzo in fonte["urls"]:
        for pagina in range(1, int(fonte.get("max_pagine", 6)) + 1):
            r = rete.get(indirizzo, params={"page": pagina} if pagina > 1 else None)
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.find_all("a", href=True):
                a["href"] = https(a["href"].strip(), base) or a["href"]
            trovati = estrai_da_html(str(soup), {**fonte, "link": r"/prodotto/"})
            nuovi = [e for e in trovati if e["url"] not in voci]
            for e in nuovi:
                titolo = re.sub(r"\s+", " ", PREZZO_TESTO.sub("", e["titolo"])).strip(" -–—·|")
                if len(titolo) < 4 or e["prezzo"] is None:
                    continue
                voci[e["url"]] = _voce(fonte, slug(e["url"].split("/prodotto/")[-1])[:80], titolo, e["url"],
                                       e["prezzo"], e["valuta"], immagine=e["immagine"])
            if not nuovi:
                break  # pagina oltre l'ultima o già vista
    return list(voci.values()), False


LETTORI = {
    "shopify": leggi_shopify,
    "woocommerce": leggi_woocommerce,
    "jsonld": leggi_jsonld,
    "rss": leggi_rss,
    "html": leggi_html,
    "etsy": leggi_etsy,
    "email": leggi_email,
    "mpb": leggi_mpb,
}


def scarica(fonte, rete):
    """Restituisce (voci, completo). Se completo è vero, gli annunci della fonte non più presenti sono venduti."""
    lettore = LETTORI.get(fonte.get("tipo"))
    if not lettore:
        raise ValueError(f"tipo di fonte sconosciuto: {fonte.get('tipo')!r}")
    return lettore(fonte, rete)
