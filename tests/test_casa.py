import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import yaml
from pathlib import Path

from cacciatore import casa
from cacciatore import negozi
from test_negozi import ReteFinta

PAGINA_MPB = """<html><body><div class="lista">
<div class="card"><a href="/it-it/prodotto/sony-a7-iii"><img src="https://img.mpb.com/a.jpg">
 <span>Sony A7 III</span></a><span>10+ disponibili</span><span>1.049 €-1.299 €</span></div>
<div class="card"><a href="/it-it/prodotto/nikon-z6"><span>Nikon Z6</span></a><span>6 disponibili</span>
 <span>749 € - 899 €</span></div>
</div></body></html>"""

FONTE = {"nome": "MPB fotocamere", "tipo": "mpb", "da_casa": True, "url": "https://www.mpb.com", "paese": "IT",
         "valuta": "EUR", "urls": ["https://www.mpb.com/it-it/categoria/fotocamere-usate/fotocamere-mirrorless"],
         "max_pagine": 2, "titolo_togli": [r"\d+\+?\s*disponibil[ei]"]}


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class TestLetturaCasa(unittest.TestCase):
    def test_legge_davvero_senza_da_casa_e_pulisce_i_titoli(self):
        rete = ReteFinta({FONTE["urls"][0]: PAGINA_MPB})
        rete.motivo_robots = {}
        [ris] = casa.leggi({"fonti": [FONTE]}, rete)
        self.assertTrue(ris["ok"])
        per = {v["titolo"]: v["prezzo"] for v in ris["voci"]}
        self.assertEqual(per, {"Sony A7 III": 1049.0, "Nikon Z6": 749.0})
        json.dumps(ris)  # deve poter viaggiare come file

    def test_blocco_diventa_errore_leggibile(self):
        rete = ReteFinta({FONTE["urls"][0]: RuntimeError("403")})
        rete.motivo_robots = {"https://www.mpb.com": "il sito risponde 403 anche a robots.txt"}
        [ris] = casa.leggi({"fonti": [FONTE]}, rete)
        self.assertFalse(ris["ok"])
        self.assertIn("403", ris["errore"])

    def test_ignora_le_fonti_normali(self):
        rete = ReteFinta({})
        rete.motivo_robots = {}
        self.assertEqual(casa.leggi({"fonti": [{**FONTE, "da_casa": False}]}, rete), [])


class TestFileDaCasa(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.fonte = {**FONTE, "file_casa": os.path.join(self.dir, "mpb.json")}

    def scrivi(self, **k):
        dati = {"nome": FONTE["nome"], "letto": iso(datetime.now(timezone.utc)), "ok": True, "errore": None,
                "completo": False, "voci": [{"id": "x", "titolo": "Sony A7 III"}], **k}
        Path(self.fonte["file_casa"]).write_text(json.dumps(dati), encoding="utf-8")

    def test_manca_il_file(self):
        with self.assertRaisesRegex(RuntimeError, "PC di casa"):
            negozi.scarica(self.fonte, None)

    def test_file_buono(self):
        self.scrivi()
        voci, completo = negozi.scarica(self.fonte, None)
        self.assertEqual(voci[0]["titolo"], "Sony A7 III")
        self.assertFalse(completo)

    def test_file_vecchio(self):
        self.scrivi(letto=iso(datetime.now(timezone.utc) - timedelta(hours=60)))
        with self.assertRaisesRegex(RuntimeError, "vecchi di 60 ore"):
            negozi.scarica(self.fonte, None)

    def test_errore_da_casa(self):
        self.scrivi(ok=False, errore="403", voci=[])
        with self.assertRaisesRegex(RuntimeError, "403"):
            negozi.scarica(self.fonte, None)

    def test_percorso_coincide_con_quello_inviato(self):
        self.assertEqual(negozi.file_casa("MPB obiettivi").replace(os.sep, "/"), "docs/data/casa/mpb-obiettivi.json")


class TestInvio(unittest.TestCase):
    def test_aggiorna_con_sha(self):
        get = mock.Mock(status_code=200, json=lambda: {"sha": "abc"})
        put = mock.Mock(status_code=200)
        with mock.patch.object(casa.requests, "get", return_value=get), \
                mock.patch.object(casa.requests, "put", return_value=put) as p:
            casa.invia({"nome": "MPB fotocamere", "voci": []}, "tok")
        url = p.call_args.args[0]
        self.assertTrue(url.endswith("/contents/docs/data/casa/mpb-fotocamere.json"))
        self.assertEqual(p.call_args.kwargs["json"]["sha"], "abc")

    def test_token_rifiutato(self):
        with mock.patch.object(casa.requests, "get", return_value=mock.Mock(status_code=401)):
            with self.assertRaisesRegex(RuntimeError, "token"):
                casa.invia({"nome": "MPB fotocamere", "voci": []}, "tok")


class TestConfigCasa(unittest.TestCase):
    def test_mpb_letto_da_casa(self):
        cfg = yaml.safe_load((Path(__file__).parent.parent / "config.yaml").read_text(encoding="utf-8"))
        mpb = [f for f in cfg["fonti"] if f["nome"].startswith("MPB")]
        self.assertEqual(len(mpb), 2)
        self.assertTrue(all(f["da_casa"] and f.get("attivo", True) for f in mpb))
