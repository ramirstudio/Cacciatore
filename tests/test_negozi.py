import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from cacciatore import negozi
from cacciatore.main import esegui
from cacciatore.rete import Rete, Vietato

RADICE = Path(__file__).parent.parent
CFG = yaml.safe_load((RADICE / "config.yaml").read_text(encoding="utf-8"))
TASSI = {"EUR": 1.0, "USD": 1.15, "GBP": 0.86, "JPY": 170.0}
ADESSO = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)


class Risposta:
    def __init__(self, corpo):
        self.content = corpo if isinstance(corpo, bytes) else (corpo if isinstance(corpo, str) else json.dumps(corpo)).encode()
        self.text = self.content.decode()

    def json(self):
        return json.loads(self.text)


class ReteFinta:
    def __init__(self, pagine):
        self.pagine = pagine
        self.chiamate = []

    def get(self, url, params=None):
        self.chiamate.append((url, params))
        chiave = url
        if params and "page" in params:
            chiave = f"{url}#{params['page']}"
        if chiave not in self.pagine:
            chiave = url
        corpo = self.pagine[chiave]
        if isinstance(corpo, Exception):
            raise corpo
        return Risposta(corpo)


def prodotto(handle, titolo, prezzo, varianti=None, **extra):
    return {"handle": handle, "title": titolo, "tags": [], "product_type": "",
            "variants": varianti or [{"title": "Default Title", "price": prezzo, "available": True}],
            "images": [{"src": f"https://cdn.example.com/{handle}.jpg"}], **extra}


def fonte_shopify(**k):
    return {"nome": "Negozio Prova", "tipo": "shopify", "url": "https://prova.example.com", "paese": "NL",
            "valuta": "EUR", **k}


class TestParsePrezzo(unittest.TestCase):
    def test_formati(self):
        casi = {"€ 1.234,56": 1234.56, "1,234.56": 1234.56, "1 299 zł": 1299.0, "89,90 €": 89.9,
                "£120": 120.0, "1.200": 1200.0, "45.5": 45.5, "gratis": None, 12: 12.0}
        for testo, atteso in casi.items():
            self.assertEqual(negozi.parse_prezzo(testo), atteso, testo)

    def test_valuta(self):
        self.assertEqual(negozi.valuta_da_testo("12 990 Ft", "EUR"), "HUF")
        self.assertEqual(negozi.valuta_da_testo("£50", "EUR"), "GBP")
        self.assertEqual(negozi.valuta_da_testo("50", "PLN"), "PLN")


class TestAdattatori(unittest.TestCase):
    def test_shopify(self):
        rete = ReteFinta({"https://prova.example.com/products.json": {"products": [
            prodotto("zorki-4", "Zorki 4 rangefinder", "85.00"),
            prodotto("esaurito", "Kiev 88", "300.00", [{"title": "x", "price": "300.00", "available": False}]),
            prodotto("varianti", "Helios 44-2", "40.00", [
                {"title": "Used - Good", "price": "60.00", "available": True},
                {"title": "Used - Fair", "price": "40.00", "available": True}]),
            prodotto("nuovo", "Lomo LC-A", "399.00", [{"title": "New", "price": "399.00", "available": True}]),
        ]}})
        voci, completo = negozi.scarica(fonte_shopify(), rete)
        per = {v["titolo"]: v for v in voci}
        self.assertTrue(completo)
        self.assertNotIn("Kiev 88", per)
        self.assertEqual(per["Helios 44-2"]["prezzo"], 40.0)
        self.assertEqual(per["Helios 44-2"]["condizione"], "Used")
        self.assertTrue(per["Lomo LC-A"]["nuovo"])
        self.assertFalse(per["Zorki 4 rangefinder"]["nuovo"])
        self.assertEqual(per["Zorki 4 rangefinder"]["url"], "https://prova.example.com/products/zorki-4")

    def test_shopify_pagine_e_limite(self):
        pieno = {"products": [prodotto(f"p{i}", f"Prodotto {i}", "10") for i in range(100)]}
        rete = ReteFinta({"https://prova.example.com/products.json#1": pieno,
                          "https://prova.example.com/products.json#2": {"products": [prodotto("ultimo", "Ultimo", "5")]}})
        voci, completo = negozi.scarica(fonte_shopify(), rete)
        self.assertEqual(len(voci), 101)
        self.assertTrue(completo)
        rete = ReteFinta({"https://prova.example.com/products.json": pieno})
        _, completo = negozi.scarica(fonte_shopify(max_pagine=2), rete)
        self.assertFalse(completo)  # limite raggiunto: l'elenco può essere parziale

    def test_woocommerce(self):
        rete = ReteFinta({"https://woo.example.com/wp-json/wc/store/v1/products": [
            {"id": 7, "name": "Praktica MTL3 &amp; Pancolar", "permalink": "https://woo.example.com/p/7",
             "is_in_stock": True, "prices": {"price": "8900", "currency_code": "EUR", "currency_minor_unit": 2},
             "categories": [{"name": "Gebraucht"}], "tags": [], "images": [{"src": "https://woo.example.com/7.jpg"}]},
            {"id": 8, "name": "Fuori", "permalink": "https://woo.example.com/p/8", "is_in_stock": False,
             "prices": {"price": "100", "currency_minor_unit": 2}}]})
        voci, _ = negozi.scarica({"nome": "Woo", "tipo": "woocommerce", "url": "https://woo.example.com", "paese": "DE"}, rete)
        self.assertEqual(len(voci), 1)
        self.assertEqual(voci[0]["prezzo"], 89.0)
        self.assertEqual(voci[0]["titolo"], "Praktica MTL3 & Pancolar")
        self.assertEqual(voci[0]["condizione"], "Used")

    def test_jsonld(self):
        html = """<html><head><script type="application/ld+json">
        {"@context":"https://schema.org","@graph":[
          {"@type":"Product","name":"Pentacon Six TL","url":"/prodotto/pentacon","image":"/img/p.jpg",
           "offers":{"@type":"Offer","price":"210.00","priceCurrency":"EUR","availability":"https://schema.org/InStock"}},
          {"@type":"Product","name":"Venduto","url":"/prodotto/venduto",
           "offers":{"price":"10","availability":"https://schema.org/OutOfStock"}}]}
        </script></head></html>"""
        rete = ReteFinta({"https://j.example.com/elenco": html})
        voci, _ = negozi.scarica({"nome": "J", "tipo": "jsonld", "url": "https://j.example.com",
                                  "urls": ["https://j.example.com/elenco"], "paese": "FR"}, rete)
        self.assertEqual([v["titolo"] for v in voci], ["Pentacon Six TL"])
        self.assertEqual(voci[0]["url"], "https://j.example.com/prodotto/pentacon")
        self.assertEqual(voci[0]["immagine"], "https://j.example.com/img/p.jpg")

    def test_rss(self):
        xml = """<?xml version="1.0"?><rss xmlns:media="http://search.yahoo.com/mrss/"><channel>
        <item><title>Vendo Jupiter-9 85mm</title><link>https://forum.example.com/t/1</link>
        <description>Ottica in buono stato, 150 € trattabili</description><guid>t1</guid>
        <media:content url="https://forum.example.com/1.jpg"/></item>
        <item><title>Cerco Zenit</title><link>https://forum.example.com/t/2</link><description>nessun prezzo</description></item>
        </channel></rss>"""
        rete = ReteFinta({"https://forum.example.com/feed": xml})
        voci, _ = negozi.scarica({"nome": "Forum", "tipo": "rss", "url": "https://forum.example.com",
                                  "urls": ["https://forum.example.com/feed"], "paese": "CZ", "valuta": "CZK"}, rete)
        self.assertEqual(len(voci), 1)
        self.assertEqual(voci[0]["prezzo"], 150.0)
        self.assertEqual(voci[0]["valuta"], "EUR")
        self.assertEqual(voci[0]["immagine"], "https://forum.example.com/1.jpg")

    def test_html(self):
        html = """<div class="p"><a class="t" href="/a/1">Kiev 60 con Volna-3</a><span class="pr">1 250 zł</span>
        <img src="/i/1.jpg"></div><div class="p"><a class="t" href="/a/2">Senza prezzo</a><span class="pr">chiedi</span></div>"""
        rete = ReteFinta({"https://h.example.com/usato": html})
        voci, _ = negozi.scarica({"nome": "H", "tipo": "html", "url": "https://h.example.com", "urls": ["https://h.example.com/usato"],
                                  "paese": "PL", "valuta": "PLN",
                                  "selettori": {"voce": ".p", "titolo": ".t", "prezzo": ".pr", "immagine": "img"}}, rete)
        self.assertEqual(len(voci), 1)
        self.assertEqual(voci[0]["prezzo"], 1250.0)
        self.assertEqual(voci[0]["valuta"], "PLN")
        self.assertEqual(voci[0]["url"], "https://h.example.com/a/1")

    def test_tipo_sconosciuto(self):
        with self.assertRaises(ValueError):
            negozi.scarica({"nome": "X", "tipo": "boh"}, ReteFinta({}))


class SessioneFinta:
    def __init__(self, robots, stato=200):
        self.headers = {}
        self.robots = robots
        self.stato = stato
        self.richieste = []

    def get(self, url, timeout=None):
        self.richieste.append(url)

        class R:
            pass
        r = R()
        if url.endswith("/robots.txt"):
            r.status_code, r.text, r.content, r.headers = self.stato, self.robots, self.robots.encode(), {}
        else:
            r.status_code, r.text, r.content, r.headers = 200, "ok", b"ok", {}
        return r


class TestRete(unittest.TestCase):
    def test_robots_vieta(self):
        s = SessioneFinta("User-agent: *\nDisallow: /privato\n")
        rete = Rete(pausa=0, sessione=s)
        self.assertTrue(rete.permesso("https://x.example.com/products.json"))
        self.assertFalse(rete.permesso("https://x.example.com/privato/a"))
        with self.assertRaises(Vietato):
            rete.get("https://x.example.com/privato/a")
        self.assertNotIn("https://x.example.com/privato/a", s.richieste)

    def test_robots_403_blocca_tutto(self):
        rete = Rete(pausa=0, sessione=SessioneFinta("", stato=403))
        self.assertFalse(rete.permesso("https://x.example.com/products.json"))

    def test_robots_assente_permette(self):
        rete = Rete(pausa=0, sessione=SessioneFinta("", stato=404))
        self.assertTrue(rete.permesso("https://x.example.com/products.json"))


def cfg_negozi(**fonte):
    cfg = json.loads(json.dumps(CFG))
    cfg["fonti"] = [{"nome": "Negozio Prova", "tipo": "shopify", "url": "https://prova.example.com", "paese": "NL",
                     "valuta": "EUR", "ogni_minuti": 120, **fonte}]
    cfg["ricerche"] = []
    return cfg


class Tg:
    def __init__(self):
        self.messaggi = []

    def annuncio(self, testo, foto=None):
        self.messaggi.append(testo)

    def testo(self, testo):
        self.messaggi.append(testo)


class TestCicloNegozi(unittest.TestCase):
    def giro(self, tmp, cfg, elenco, adesso, tg):
        def scarica(f):
            if isinstance(elenco, Exception):
                raise elenco
            return elenco
        return esegui(cfg, str(Path(tmp) / "items.json"), None, None, tg, adesso, TASSI, scarica_fonte=scarica)

    def voce(self, ident, titolo, prezzo):
        return negozi._voce({"nome": "Negozio Prova", "paese": "NL"}, ident, titolo,
                            f"https://prova.example.com/products/{ident}", prezzo, "EUR")

    def test_primo_giro_silenzioso_poi_novita(self):
        cfg = cfg_negozi()
        with tempfile.TemporaryDirectory() as tmp:
            tg = Tg()
            base = [(self.voce("a", "Zorki 1 rangefinder", 90.0)), (self.voce("b", "Helios 44-2 58mm", 40.0))]
            out = self.giro(tmp, cfg, (base, True), ADESSO, tg)
            self.assertEqual(len(out["items"]), 2)
            self.assertEqual(tg.messaggi, [])                     # nessun avviso al primo giro
            self.assertTrue(out["stato_fonti"]["Negozio Prova"]["ok"])

            dopo = ADESSO + timedelta(hours=3)
            nuovo = base + [self.voce("c", "Kiev 60 con Volna-3 80mm", 120.0)]
            out = self.giro(tmp, cfg, (nuovo, True), dopo, tg)
            self.assertEqual(len(out["items"]), 3)
            self.assertGreaterEqual(len(tg.messaggi), 1)          # la novità avvisa
            self.assertIn("Negozio Prova", tg.messaggi[0])

    def test_venduto_sparisce(self):
        cfg = cfg_negozi()
        with tempfile.TemporaryDirectory() as tmp:
            tg = Tg()
            due = [self.voce("a", "Zorki 1 rangefinder", 90.0), self.voce("b", "Helios 44-2 58mm", 40.0)]
            self.giro(tmp, cfg, (due, True), ADESSO, tg)
            out = self.giro(tmp, cfg, (due[:1], True), ADESSO + timedelta(hours=3), tg)
            self.assertEqual([a["id"] for a in out["items"]], ["negozio-prova:a"])
            # elenco parziale: nulla viene cancellato
            out = self.giro(tmp, cfg, ([], False), ADESSO + timedelta(hours=6), tg)
            self.assertEqual(len(out["items"]), 1)

    def test_ogni_minuti(self):
        cfg = cfg_negozi(ogni_minuti=120)
        with tempfile.TemporaryDirectory() as tmp:
            chiamate = []

            def scarica(f):
                chiamate.append(1)
                return [self.voce("a", "Zorki 1 rangefinder", 90.0)], True
            p = str(Path(tmp) / "items.json")
            esegui(cfg, p, None, None, Tg(), ADESSO, TASSI, scarica_fonte=scarica)
            esegui(cfg, p, None, None, Tg(), ADESSO + timedelta(minutes=30), TASSI, scarica_fonte=scarica)
            self.assertEqual(len(chiamate), 1)
            esegui(cfg, p, None, None, Tg(), ADESSO + timedelta(minutes=125), TASSI, scarica_fonte=scarica)
            self.assertEqual(len(chiamate), 2)

    def test_fonte_che_fallisce_non_ferma_le_altre(self):
        cfg = cfg_negozi()
        cfg["fonti"].append({"nome": "Altro", "tipo": "shopify", "url": "https://altro.example.com", "paese": "DE", "valuta": "EUR"})
        with tempfile.TemporaryDirectory() as tmp:
            def scarica(f):
                if f["nome"] == "Negozio Prova":
                    raise Vietato("robots.txt vieta")
                return [negozi._voce(f, "z", "Zenit 11 con Helios", "https://altro.example.com/products/z", 50.0, "EUR")], True
            out = esegui(cfg, str(Path(tmp) / "items.json"), None, None, Tg(), ADESSO, TASSI, scarica_fonte=scarica)
            self.assertFalse(out["stato_fonti"]["Negozio Prova"]["ok"])
            self.assertIn("robots", out["stato_fonti"]["Negozio Prova"]["errore"])
            self.assertTrue(out["stato_fonti"]["Altro"]["ok"])
            self.assertEqual(len(out["items"]), 1)

    def test_scarti(self):
        cfg = cfg_negozi()
        with tempfile.TemporaryDirectory() as tmp:
            voci = [self.voce("film", "Kodak Portra 400 film 36 exp", 12.0),
                    self.voce("nuova", "Lomo LC-A", 399.0)]
            voci[1]["nuovo"] = True
            voci.append(self.voce("ok", "Zorki 4 rangefinder", 80.0))
            out = self.giro(tmp, cfg, (voci, True), ADESSO, Tg())
            self.assertEqual([a["id"] for a in out["items"]], ["negozio-prova:ok"])


class TestVerifica(unittest.TestCase):
    def test_controlla(self):
        from cacciatore import verifica

        class R(ReteFinta):
            def permesso(self, url):
                return True
        rete = R({"https://prova.example.com/products.json": {"products": [
            prodotto("a", "Zorki 4 rangefinder", "85.00"), prodotto("b", "Tripod carbon", "60.00")]}})
        e = verifica.controlla(fonte_shopify(), CFG, rete)
        self.assertTrue(e["ok"])
        self.assertEqual((e["letti"], e["rilevanti"]), (2, 1))
        rete = R({"https://prova.example.com/products.json": Vietato("no")})
        e = verifica.controlla(fonte_shopify(), CFG, rete)
        self.assertFalse(e["ok"])
        self.assertIn("vieta", e["nota"])


if __name__ == "__main__":
    unittest.main()
