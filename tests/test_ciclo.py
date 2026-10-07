import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import yaml

from cacciatore.main import esegui, piano_ricerche

RADICE = Path(__file__).parent.parent
CFG = yaml.safe_load((RADICE / "config.yaml").read_text(encoding="utf-8"))
FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "ebay_sample.json").read_text(encoding="utf-8"))
TASSI = {"EUR": 1.0, "USD": 1.15, "GBP": 0.86, "JPY": 170.0}
ADESSO = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


class TelegramFinto:
    def __init__(self):
        self.messaggi = []

    def annuncio(self, testo, foto=None):
        self.messaggi.append(testo)

    def testo(self, testo):
        self.messaggi.append(testo)


def una_sola_volta():
    stato = {"n": 0}

    def cerca(q, mkt, paese):
        stato["n"] += 1
        return FIXTURE if stato["n"] == 1 else []

    return cerca


class TestCiclo(unittest.TestCase):
    def esegui(self, tmp, telegram, adesso=ADESSO, cerca=None):
        return esegui(CFG, str(Path(tmp) / "items.json"), cerca or una_sola_volta(), None, telegram, adesso, TASSI)

    def test_ciclo_completo(self):
        with tempfile.TemporaryDirectory() as tmp:
            tg = TelegramFinto()
            out = self.esegui(tmp, tg)
            per_id = {a["id"]: a for a in out["items"]}

            self.assertNotIn("ebay:v1|1004|0", per_id)             # poster scartato
            self.assertEqual(len(out["items"]), 13)
            self.assertNotIn("venditore_riservato", json.dumps(out))  # nome venditore mai salvato

            proto = per_id["ebay:v1|1001|0"]
            self.assertGreaterEqual(proto["punteggio"], 5)
            self.assertEqual(proto["totale_eur"], 194.0)             # UE: 180 + 14

            fujica = per_id["ebay:v1|1002|0"]
            self.assertTrue(fujica["extra_ue"])
            self.assertTrue(fujica["spedizione_stimata"])
            self.assertGreater(fujica["totale_eur"], fujica["prezzo_eur"] * 1.22)

            sospetto = per_id["ebay:v1|1013|0"]
            self.assertTrue(any("whatsapp" in x for x in sospetto["avvisi"]))
            self.assertTrue(any("feedback" in x for x in sospetto["avvisi"]))

            asta = per_id["ebay:v1|1014|0"]
            self.assertTrue(asta["asta"])
            self.assertFalse(asta["affare"])

    def test_affare_sulla_mediana(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.esegui(tmp, TelegramFinto())
            per_id = {a["id"]: a for a in out["items"]}
            self.assertTrue(per_id["ebay:v1|1013|0"]["affare"])
            self.assertFalse(per_id["ebay:v1|1006|0"]["affare"])

    def test_avvisi_una_volta_sola(self):
        with tempfile.TemporaryDirectory() as tmp:
            tg = TelegramFinto()
            self.esegui(tmp, tg)
            primi = len(tg.messaggi)
            self.assertGreaterEqual(primi, 3)  # prototipo, Trioplan, affare Helios
            testo = "\n".join(tg.messaggi)
            self.assertIn("Prototyp", testo)
            self.assertNotIn("Poster", testo)
            tg2 = TelegramFinto()
            self.esegui(tmp, tg2, cerca=una_sola_volta())
            self.assertEqual(tg2.messaggi, [])

    def test_pulizia_vecchi(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.esegui(tmp, None)
            dopo = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
            out = self.esegui(tmp, None, adesso=dopo, cerca=lambda q, m, p: [])
            self.assertEqual(out["items"], [])

    def test_errore_di_una_ricerca_non_blocca(self):
        with tempfile.TemporaryDirectory() as tmp:
            stato = {"n": 0}

            def cerca(q, mkt, paese):
                stato["n"] += 1
                if stato["n"] == 1:
                    raise RuntimeError("eBay giù")
                return FIXTURE if stato["n"] == 2 else []

            out = self.esegui(tmp, None, cerca=cerca)
            self.assertEqual(len(out["items"]), 13)

    def test_rotazione_copre_tutto(self):
        viste = set()
        for slot in range(0, 12):
            adesso = datetime.fromtimestamp(slot * 1800, tz=timezone.utc)
            viste.update((i, p) for i, p, _ in piano_ricerche(CFG, adesso))
        totale = len(CFG["ricerche"]) * (len(CFG["paesi"]) - ("IT" in CFG["paesi"]))
        self.assertEqual(len(viste), totale)


if __name__ == "__main__":
    unittest.main()
