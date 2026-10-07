import unittest

from cacciatore.prezzi import arrivo_a_casa, in_euro

IMP = {"iva_importazione": 0.22, "soglia_sdoganamento_eur": 150, "costo_sdoganamento_eur": 12, "dazio": 0.0}


class TestPrezzi(unittest.TestCase):
    def test_conversione(self):
        self.assertEqual(in_euro(1700, "JPY", {"JPY": 170.0}), 10.0)
        self.assertIsNone(in_euro(None, "EUR", {"EUR": 1.0}))

    def test_ue_nessun_extra(self):
        self.assertEqual(arrivo_a_casa(100, 10, "RO", IMP), (110.0, False))

    def test_extra_ue_sotto_soglia(self):
        totale, extra = arrivo_a_casa(100, 20, "JP", IMP)
        self.assertEqual(totale, 146.4)  # 120 + 22%
        self.assertTrue(extra)

    def test_extra_ue_sopra_soglia(self):
        totale, _ = arrivo_a_casa(200, 30, "GB", IMP)
        self.assertEqual(totale, 230 * 1.22 + 12 if False else round(230 * 1.22 + 12, 2))


if __name__ == "__main__":
    unittest.main()
