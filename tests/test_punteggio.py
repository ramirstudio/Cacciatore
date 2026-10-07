import unittest
from pathlib import Path

import yaml

from cacciatore.punteggio import Valutatore, tipo_prodotto

CFG = yaml.safe_load((Path(__file__).parent.parent / "config.yaml").read_text(encoding="utf-8"))


class TestPunteggio(unittest.TestCase):
    def setUp(self):
        self.v = Valutatore(CFG)

    def test_parola_dentro_altra_parola_non_conta(self):
        self.assertEqual(self.v.valuta("Federal Reserve book")[0], 0)

    def test_modello_comune_vale_poco(self):
        p, termini, _ = self.v.valuta("Helios 44-2 58mm f/2 M42 lens")
        self.assertEqual(p, 1)
        self.assertEqual(termini, ["helios"])

    def test_modello_specifico_assorbe_il_generico(self):
        p, termini, principale = self.v.valuta("Kiev 60 medium format")
        self.assertEqual(termini, ["kiev 60"])
        self.assertEqual(p, 3)
        self.assertEqual(principale, "kiev 60")

    def test_sinonimi_con_trattino_non_si_sommano(self):
        p, termini, _ = self.v.valuta("Meyer-Optik Görlitz lens")
        self.assertEqual(len([t for t in termini if "meyer" in t]), 1)
        self.assertEqual(p, 3)

    def test_punteggio_massimo_dieci(self):
        p, _, _ = self.v.valuta("Prototyp Kamera NVA Bundeswehr Kiev Vega Alpa")
        self.assertEqual(p, 10)

    def test_cirillico(self):
        p, termini, _ = self.v.valuta("Фотоаппарат Зоркий СССР")
        self.assertGreaterEqual(p, 2)

    def test_scarto(self):
        self.assertTrue(self.v.da_scartare("Poster vintage Zorki"))
        self.assertFalse(self.v.da_scartare("Zorki 4K"))

    def test_sospetti(self):
        self.assertIn("whatsapp", self.v.sospetto("Zorki, contact me on WhatsApp"))

    def test_tipo(self):
        self.assertEqual(tipo_prodotto("Helios 44-2 58mm f/2 lens"), "ottica")
        self.assertEqual(tipo_prodotto("Zorki 4K rangefinder camera"), "fotocamera")
        self.assertEqual(tipo_prodotto("Leather strap"), "altro")


if __name__ == "__main__":
    unittest.main()
