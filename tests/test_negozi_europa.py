import json
import unittest
from unittest import mock

from cacciatore import negozi
from cacciatore.negozi import PREZZO_TESTO, parse_prezzo, valuta_da_testo, leggi_pagine, leggi_vtex, leggi_shopify
from cacciatore.rete import Rete
from test_negozi import ReteFinta, Risposta


def prezzo(testo, predefinita="DEF"):
    m = PREZZO_TESTO.search(testo)
    return (parse_prezzo(m.group(0)), valuta_da_testo(m.group(0), predefinita)) if m else None


class TestValute(unittest.TestCase):
    def test_formati_europei(self):
        self.assertEqual(prezzo("15 990 SEK"), (15990.0, "SEK"))
        self.assertEqual(prezzo("kr 1 500,00", "NOK"), (1500.0, "NOK"))
        self.assertEqual(prezzo("7 500 kr", "SEK"), (7500.0, "SEK"))
        self.assertEqual(prezzo("5.080,00 DKK"), (5080.0, "DKK"))
        self.assertEqual(prezzo("2 775,00 zł"), (2775.0, "PLN"))
        self.assertEqual(prezzo("85 000 Ft"), (85000.0, "HUF"))
        self.assertEqual(prezzo("13 190 Kč"), (13190.0, "CZK"))
        self.assertEqual(prezzo("10 000 MDL"), (10000.0, "MDL"))
        self.assertEqual(prezzo("300 USD"), (300.0, "USD"))
        self.assertEqual(prezzo("229,00 € / 447,89 лв."), (229.0, "EUR"))
        self.assertEqual(prezzo("100 euro"), (100.0, "EUR"))

    def test_niente_prezzi_dentro_le_parole(self):
        for t in ["Sony A7 III 3 kropp", "Soft 2 case", "Canon 85mm f/1.8 USM", "Nikon Z 24-70 2 ronde"]:
            self.assertIsNone(PREZZO_TESTO.search(t), t)


def pagina(n, prefisso="/it/p"):
    return (f'<div class="c"><a href="https://x.example{prefisso}/sony-a7-{n}">Sony A7 {n}</a><span>{n}00 €</span></div>'
            f'<div class="c"><a href="https://x.example{prefisso}/nikon-z{n}">Nikon Z{n}</a><span>{n}50 €</span></div>')


class TestPaginazioni(unittest.TestCase):
    def fonte(self, **k):
        return {"nome": "Prova", "tipo": "pagine", "url": "https://x.example", "urls": ["https://x.example/usato"],
                "link": "/it/p/", "max_pagine": 3, **k}

    def leggi(self, pagine, **k):
        rete = ReteFinta(pagine)
        voci, _ = leggi_pagine(self.fonte(**k), rete)
        return rete, voci

    def test_virgola(self):
        rete, voci = self.leggi({"https://x.example/usato": pagina(1), "https://x.example/usato,2": pagina(2),
                                 "https://x.example/usato,3": "<html></html>"}, paginazione="virgola")
        self.assertEqual(len(voci), 4)
        self.assertEqual(rete.chiamate[1][0], "https://x.example/usato,2")

    def test_pagina_html(self):
        rete, voci = self.leggi({"https://x.example/usato": pagina(1), "https://x.example/usato/page2.html": pagina(2),
                                 "https://x.example/usato/page3.html": "<html></html>"}, paginazione="pagina_html")
        self.assertEqual(len(voci), 4)

    def test_conta_da_zero(self):
        rete, voci = self.leggi({"https://x.example/usato": pagina(1), "https://x.example/usato#1": pagina(2),
                                 "https://x.example/usato#2": "<html></html>"}, pagina_iniziale=0)
        self.assertEqual(rete.chiamate[1][1], {"page": 1})
        self.assertEqual(len(voci), 4)

    def test_valute_ammesse(self):
        html = ('<div><a href="https://x.example/it/p/canon-600d">Canon 600D</a><span>4 500 MDL</span></div>'
                '<div><a href="https://x.example/it/p/nikon-d3200">Nikon D3200</a><span>8 450 руб</span></div>'
                '<div><a href="https://x.example/it/p/sony-a6000">Sony A6000</a><span>300 USD</span></div>')
        _, voci = self.leggi({"https://x.example/usato": html}, valute_ammesse=["MDL", "USD", "EUR"], valuta="MDL", max_pagine=1)
        self.assertEqual(sorted((v["titolo"], v["valuta"]) for v in voci), [("Canon 600D", "MDL"), ("Sony A6000", "USD")])


class TestScarta(unittest.TestCase):
    def test_titoli_venduti_scartati(self):
        fonte = {"nome": "Prova", "tipo": "pagine", "url": "https://x.example", "urls": ["https://x.example/usato"],
                 "link": "/it/p/", "max_pagine": 1, "scarta": ["^\\s*MYYTY"]}
        html = ('<div><a href="https://x.example/it/p/a">MYYTY Canon R6</a><span>900 €</span></div>'
                '<div><a href="https://x.example/it/p/b">Canon R5</a><span>1900 €</span></div>')
        voci, _ = negozi.scarica(fonte, ReteFinta({"https://x.example/usato": html}))
        self.assertEqual([v["titolo"] for v in voci], ["Canon R5"])


class TestVtex(unittest.TestCase):
    def test_legge_catalogo_json(self):
        prodotti = [
            {"productId": "1", "productName": "Sony A6100 Body SH-1035890", "link": "https://www.f64.ro/sony-a6100-sh/p",
             "items": [{"images": [{"imageUrl": "https://img.f64.ro/1.jpg"}],
                        "sellers": [{"commertialOffer": {"Price": 1892.7, "AvailableQuantity": 1}}]}]},
            {"productId": "2", "productName": "Esaurito", "link": "https://www.f64.ro/x/p",
             "items": [{"sellers": [{"commertialOffer": {"Price": 100, "AvailableQuantity": 0}}]}]},
        ]
        rete = ReteFinta({"https://www.f64.ro/api/catalog_system/pub/products/search/consignatie/obiective": json.dumps(prodotti)})
        fonte = {"nome": "F64", "tipo": "vtex", "url": "https://www.f64.ro", "categorie": ["consignatie/obiective"], "valuta": "RON"}
        voci, completo = leggi_vtex(fonte, rete)
        self.assertEqual(len(voci), 1)
        self.assertEqual((voci[0]["prezzo"], voci[0]["valuta"]), (1892.7, "RON"))
        self.assertEqual(rete.chiamate[0][1], {"_from": 0, "_to": 49})


class TestShopifyTag(unittest.TestCase):
    def test_esclude_tag_pellicola(self):
        prodotti = {"products": [
            {"handle": "canon-fd-50", "title": "Canon FD 50mm", "tags": ["Usage-Film"],
             "variants": [{"title": "Default Title", "price": "80.00", "available": True}], "images": []},
            {"handle": "sony-fe-85", "title": "Sony FE 85mm", "tags": ["Usage-Digital"],
             "variants": [{"title": "Default Title", "price": "450.00", "available": True}], "images": []},
        ]}
        fonte = {"nome": "Kamerastore", "url": "https://kamerastore.com", "collezioni": ["mirrorless-lenses"],
                 "escludi_tag": ["Usage-Film"], "valuta": "EUR"}
        voci, _ = leggi_shopify(fonte, ReteFinta({"https://kamerastore.com/collections/mirrorless-lenses/products.json": json.dumps(prodotti)}))
        self.assertEqual([v["titolo"] for v in voci], ["Sony FE 85mm"])


class TestCrawlDelay(unittest.TestCase):
    def test_rispetta_il_crawl_delay(self):
        sessione = mock.Mock()
        sessione.headers = {}
        sessione.get.return_value = mock.Mock(status_code=200, text="User-agent: *\nCrawl-delay: 10\nDisallow: /cart\n")
        rete = Rete(sessione=sessione)
        self.assertTrue(rete.permesso("https://shop.example/begagnat"))
        self.assertEqual(rete.pausa_host["https://shop.example"], 10.0)


class TestCodiciArticolo(unittest.TestCase):
    def test_il_codice_non_si_attacca_al_prezzo(self):
        self.assertEqual(prezzo("SGD010018 495,00 €"), (495.0, "EUR"))
        self.assertEqual(prezzo("SGD010019 449,95 €"), (449.95, "EUR"))
        self.assertEqual(prezzo("18 495 €"), (18495.0, "EUR"))

    def test_parole_doppie_nel_titolo(self):
        html = '<div><a href="https://x.example/it/p/s">Sirui Sirui 40mm T1.8</a><span>649 €</span></div>'
        fonte = {"nome": "P", "tipo": "pagine", "url": "https://x.example", "urls": ["https://x.example/u"], "link": "/it/p/", "max_pagine": 1}
        voci, _ = leggi_pagine(fonte, ReteFinta({"https://x.example/u": html}))
        self.assertEqual(voci[0]["titolo"], "Sirui 40mm T1.8")


class TestCodifica(unittest.TestCase):
    def test_utf8_senza_charset_non_diventa_latin1(self):
        testo = "Canon 580EX för Canon EOS 6D"
        sessione = mock.Mock()
        sessione.headers = {}
        risposta = mock.Mock(status_code=200, content=testo.encode("utf-8"), encoding="ISO-8859-1",
                             apparent_encoding="utf-8", headers={"Content-Type": "text/html"})
        sessione.get.return_value = risposta
        rete = Rete(sessione=sessione)
        rete._robots["https://x.example"] = mock.Mock(can_fetch=lambda *a: True)
        r = rete.get("https://x.example/p")
        self.assertEqual(r.encoding, "utf-8")


class TestFiltriModerno(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import yaml
        from pathlib import Path
        from cacciatore.punteggio import Valutatore
        cfg = yaml.safe_load((Path(__file__).parent.parent / "config.yaml").read_text(encoding="utf-8"))
        cls.v = Valutatore(cfg)

    def scartato(self, t):
        return self.v.da_scartare_moderno(t) or self.v.da_scartare(t) or self.v.da_scartare_negozio(t)

    def test_fuori_pellicola_e_accessori(self):
        for t in ["Paillard Bolex B8 – Occasion", "Käytetty Minox B filmikamera", "Leica C1 gebraucht",
                  "Canon EOS 300 + EF 28-90mm f4-5,6 silber gebraucht", "Lens Protector 77mm - Used",
                  "Canon Speedlite 580EX flash - Used", "Zoom H1 Handy Recorder - Used", "FUJI XF 1,4X TC WR",
                  "Canon Extender EF 1,4X III", "Jupio JBG-C009 för Canon EOS 6D", "Lowepro Vertex 200 AW",
                  "Jumelle à imagerie thermique Raptor RQ50LN - HIKMICRO", "Nikon Nikkor -P 105mm f/2,5 manual-Focus",
                  "Cámara analógica Leica M2 cuerpo segunda mano", "Canon EOS 500N film", "Canon EOS 1V Body"]:
            self.assertTrue(self.scartato(t), t)

    def test_restano_corpi_digitali_e_ottiche_moderne(self):
        for t in ["Nikon Z6 II Body gebraucht", "Canon EOS 5D Mark IV", "Canon EOS 50D", "Canon EOS 100D", "Canon EOS 300D",
                  "Canon EOS 3000D", "Canon EOS 1000D", "Canon EOS R5", "Sony Alpha 7 V (boîtier nu)", "Fujifilm X-T3",
                  "Canon EOS 5DS R", "Sony FE 85mm f/1.8", "Canon EOS R6 with Speedlite flash", "Nikon Z 24-70mm f/2.8 S",
                  "Sony A7 III, body", "Sony PXW-Z90 camcorder"]:
            self.assertFalse(self.scartato(t), t)


class TestPuliziaTitoliDaConfig(unittest.TestCase):
    def test_titoli_scandinavi(self):
        import re
        import yaml
        from pathlib import Path
        cfg = yaml.safe_load((Path(__file__).parent.parent / "config.yaml").read_text(encoding="utf-8"))
        fonte = next(f for f in cfg["fonti"] if f["nome"] == "Scandinavian Photo NO")
        t = "Brukt A7C II Body (åpnet vare) Sony A7C II Body (åpnet vare) Ny stand 1 års garanti"
        t = re.sub(r"^\s*Brukt\s+", "", t)
        for togli in fonte["titolo_togli"]:
            t = re.sub(togli, "", t, flags=re.I)
        self.assertEqual(re.sub(r"\s+", " ", t).strip(), "A7C II Body Sony A7C II Body")


class TestSubito(unittest.TestCase):
    def test_pulisci_ricerca(self):
        from cacciatore.negozi import pulisci_ricerca
        u = pulisci_ricerca("https://www.subito.it/annunci-italia/vendita/fotografia/?kxconfid=x&amp;order=datedesc&amp;q=sony+ottiche&amp;utm_term=1")
        self.assertEqual(u, "https://www.subito.it/annunci-italia/vendita/fotografia/?q=sony+ottiche&order=datedesc")

    def test_legge_next_data(self):
        import json
        from cacciatore.negozi import leggi_subito
        ann = {"subject": "Sony FE 85mm", "urn": "id:ad:1", "date": "2026-10-12 16:40:12",
               "urls": {"default": "https://www.subito.it/fotografia/sony-fe-85-milano-612345678.htm"},
               "features": {"/price": {"uri": "/price", "values": [{"key": "390", "value": "390 €"}]}}}
        pagina = '<script id="__NEXT_DATA__" type="application/json">' + json.dumps({"a": {"list": [{"item": ann}]}}) + "</script>"

        class R:
            text = pagina

        class Rete:
            def get(self, url, params=None):
                return R()
        voci, completo = leggi_subito({"nome": "Subito", "paese": "IT", "file_ricerche": "/nessuno.json",
                                       "ricerche": ["https://www.subito.it/annunci-italia/vendita/fotografia/?q=x"]}, Rete())
        self.assertEqual(len(voci), 1)
        self.assertEqual(voci[0]["prezzo"], 390.0)
        self.assertEqual(voci[0]["pubblicato"], "2026-10-12T14:40:00Z")
        self.assertFalse(completo)
