"""Punteggio di rarità, tipo di prodotto e segnali di prudenza."""
import re
import unicodedata

TIPO_OTTICA = re.compile(
    r"(?<![a-z0-9])(lens|lenses|lenzen|objektiv|objektive|obiektyw|obiectiv|objectif|objectifs|objectief|objectieven|obiettivo|obiettivi|lente|zoomlens|"
    r"helios|jupiter|industar|tair|zenitar|rubinar|volna|kaleinar|peleng|trioplan|primoplan|biotar|"
    r"\d{2,3}\s?mm\s?f\s?/?\s?\d|f\s?/\s?\d(\.\d)?\s?\d{2,3}\s?mm)(?![a-z0-9])"
)
TIPO_FOTOCAMERA = re.compile(
    r"(?<![a-z0-9])(camera|kamera|aparat|aparat foto|fotoaparat|fotocamera|fotocamere|appareil|slr|dslr|rangefinder|"
    r"boitier nu|boitier|gehause|gehaeuse|systeemcamera|spiegelreflexcamera|mirrorless|"
    r"twin lens|tlr|rolleiflex|zorki|fed|kiev|zenit|lubitel|smena|horizont|pentacon six|mamiya|bronica|holga)"
    r"(?![a-z0-9])"
)


def normalizza(testo):
    """Minuscolo, senza accenti latini, spazi singoli. Il cirillico resta com'è."""
    t = unicodedata.normalize("NFKD", (testo or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t).strip()


def _chiave(termine):
    return re.sub(r"[\s\-]+", " ", normalizza(termine))


def _regex(termine):
    parti = [re.escape(x) for x in _chiave(termine).split(" ")]
    return re.compile(r"(?<![^\W_])" + r"[\s\-]?".join(parti) + r"(?![^\W_])")


class Valutatore:
    def __init__(self, cfg):
        p = cfg["punteggio"]
        unici = {}
        for t, w in p["termini"].items():
            k = _chiave(t)
            if k not in unici or int(w) > unici[k][1]:
                unici[k] = (t, int(w))
        for t in p.get("comuni", []):
            k = _chiave(t)
            if k not in unici:
                unici[k] = (t, 0)  # modello diffuso: serve a confrontare i prezzi, non dà punteggio
        self.termini = [(t, w, _regex(t)) for t, w in unici.values()]
        self.escludi = [_regex(x) for x in p.get("escludi", [])]
        self.sospetti = [(x, _regex(x)) for x in p.get("sospetti", [])]
        self.escludi_moderno = [_regex(x) for x in cfg.get("moderno", {}).get("escludi_titolo", [])]
        self.escludi_vintage = [_regex(x) for x in cfg.get("moderno", {}).get("escludi_vintage", [])]
        self.escludi_negozio = [_regex(x) for x in cfg.get("negozi", {}).get("escludi_titolo", [])]

    def da_scartare(self, titolo):
        t = normalizza(titolo)
        return any(r.search(t) for r in self.escludi)

    def da_scartare_moderno(self, titolo):
        t = normalizza(titolo)
        if any(r.search(t) for r in self.escludi_vintage):  # materiale analogico: sul titolo intero
            return True
        # gli accessori in dotazione ("body + battery and charger") non rendono accessorio l'annuncio:
        # conta solo la parte prima di "with / incl / + / con / mit"
        t = re.split(r"\s(?:with|incl\.?|including|plus|con|mit|avec|inkl\.?|e|and)\s|\s\+\s?|,", t)[0]
        return any(r.search(t) for r in self.escludi_moderno)

    def da_scartare_negozio(self, titolo):
        t = normalizza(titolo)
        return any(r.search(t) for r in self.escludi_negozio)

    def valuta(self, titolo):
        """Restituisce (punteggio 0-10, termini trovati, termine principale)."""
        t = normalizza(titolo)
        trovati = [(nome, peso) for nome, peso, r in self.termini if r.search(t)]
        # un termine contenuto in un altro più specifico non conta due volte
        nomi = [n for n, _ in trovati]
        puliti = [
            (n, w) for n, w in trovati
            if not any(n != m and _chiave(n) in _chiave(m) for m in nomi)
        ]
        punteggio = min(10, sum(w for _, w in puliti))
        principale = max(puliti, key=lambda x: x[1])[0] if puliti else None
        return punteggio, [n for n, _ in puliti], principale

    def sospetto(self, titolo):
        t = normalizza(titolo)
        return [nome for nome, r in self.sospetti if r.search(t)]


def tipo_prodotto(titolo):
    t = normalizza(titolo)
    if TIPO_OTTICA.search(t):
        return "ottica"
    if TIPO_FOTOCAMERA.search(t):
        return "fotocamera"
    return "altro"
