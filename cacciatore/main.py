"""Ciclo di ricerca: interroga le fonti, valuta gli annunci, aggiorna l'archivio, manda gli avvisi."""
import argparse
import json
import logging
import re
import os
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from . import allegro as mod_allegro
from . import ebay as mod_ebay
from . import negozi as mod_negozi
from .rete import Rete
from .prezzi import PAESI_UE, arrivo_a_casa, in_euro, scarica_tassi
from .punteggio import Valutatore, tipo_prodotto
from .telegram import Telegram, formatta_avviso

log = logging.getLogger("cacciatore")

NOMI_PAESI = {
    "RO": "Romania", "BG": "Bulgaria", "PL": "Polonia", "CZ": "Repubblica Ceca", "SK": "Slovacchia",
    "HU": "Ungheria", "HR": "Croazia", "SI": "Slovenia", "EE": "Estonia", "LV": "Lettonia",
    "LT": "Lituania", "GR": "Grecia", "DE": "Germania", "AT": "Austria", "GB": "Regno Unito",
    "JP": "Giappone", "CN": "Cina", "HK": "Hong Kong", "FR": "Francia", "ES": "Spagna",
    "NL": "Paesi Bassi", "BE": "Belgio", "IT": "Italia", "US": "Stati Uniti",
    "FI": "Finlandia", "SE": "Svezia", "DK": "Danimarca", "IE": "Irlanda", "PT": "Portogallo",
    "LU": "Lussemburgo", "CY": "Cipro", "MT": "Malta", "CH": "Svizzera", "NO": "Norvegia",
    "TR": "Turchia", "KR": "Corea del Sud", "TW": "Taiwan", "CA": "Canada", "AU": "Australia",
    "RS": "Serbia", "UA": "Ucraina", "RU": "Russia", "BY": "Bielorussia",
    "ID": "Indonesia", "ZA": "Sudafrica", "VN": "Vietnam", "TH": "Thailandia", "MY": "Malesia",
    "SG": "Singapore", "PH": "Filippine", "NZ": "Nuova Zelanda",
}
MAX_ARCHIVIO = 4000          # annunci eBay
MAX_ARCHIVIO_NEGOZI = 3000   # negozi ed email: non vanno mai tagliati a favore di eBay
SLOT_MINUTI = 30


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def carica_json(percorso, predefinito):
    p = Path(percorso)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log.warning("File %s illeggibile, riparto da zero.", p)
    return predefinito


def piano_ricerche(cfg, adesso):
    """Elenco delle chiamate eBay da fare in questa esecuzione, a rotazione.

    I paesi vicini (cfg["paesi"]) e quelli lontani (cfg["paesi_lontani"], con più dogana e più rischio) ruotano
    separatamente: i lontani hanno una quota fissa di chiamate e solo i gruppi che non hanno lontani: false.
    """
    esclusi = set(cfg["generale"].get("paesi_esclusi", []))
    gruppi = cfg["ricerche"]
    lontani_cfg = {p: m for p, m in cfg.get("paesi_lontani", {}).items() if p not in esclusi}
    vicini_cfg = {p: m for p, m in cfg["paesi"].items() if p not in esclusi}
    moderno = {i for i, g in enumerate(gruppi) if g.get("modalita") == "moderno"}
    vicini = [(i, p, m) for i in range(len(gruppi)) if i not in moderno for p, m in vicini_cfg.items()]
    lontani = [(i, p, m) for i in range(len(gruppi)) if i not in moderno and gruppi[i].get("lontani", True)
               for p, m in lontani_cfg.items()]
    # il Moderno ha una coda propria, così non viene sommerso dal vintage: tutti i paesi vicini e, per i gruppi
    # che lo permettono, anche i lontani
    nuovi = [(i, p, m) for i in sorted(moderno)
             for p, m in list(vicini_cfg.items()) + (list(lontani_cfg.items()) if gruppi[i].get("lontani", True) else [])]
    totale = cfg["generale"]["chiamate_per_esecuzione"]
    q_mod = min(int(cfg["generale"].get("quota_moderno", 0)), totale) if nuovi else 0
    q_lon = min(int(cfg["generale"].get("quota_lontani", 0)), totale - q_mod) if lontani else 0
    if not q_mod:  # senza quota dedicata il Moderno ruota insieme agli altri
        vicini = sorted(vicini + nuovi, key=lambda x: x[0])
        nuovi = []
    slot = int(adesso.timestamp() // (SLOT_MINUTI * 60))
    piano = []
    for elenco, budget in ((vicini, totale - q_mod - q_lon), (lontani, q_lon), (nuovi, q_mod)):
        if not elenco or budget <= 0:
            continue
        budget = min(budget, len(elenco))
        inizio = (slot * budget) % len(elenco)
        piano += [elenco[(inizio + k) % len(elenco)] for k in range(budget)]
    return piano


def elabora(a, gruppo, valutatore, tassi, cfg):
    """Aggiunge punteggio, prezzi in euro, totale stimato e avvisi di prudenza."""
    imp = cfg["importazione"]
    punteggio, termini, principale = valutatore.valuta(a["titolo"])
    a["punteggio"] = punteggio
    a["motivi"] = termini
    a["tipo"] = tipo_prodotto(a["titolo"])
    a["gruppo"] = gruppo["nome"]
    a["classico"] = bool(gruppo.get("classico"))
    a["ricerca_salvata"] = bool(gruppo.get("ricerca_salvata"))
    a["modalita"] = gruppo.get("modalita", "vintage")
    if a["modalita"] == "moderno" and a["tipo"] == "altro" and principale:
        # un modello noto vale come fotocamera, o come obiettivo se il modello è una focale (50mm, 24-70)
        a["tipo"] = "ottica" if re.search(r"\d\s?mm|\d-\d", principale) else "fotocamera"
    if principale:
        a["chiave_mercato"] = f"{principale}|{a['tipo']}"
    elif a.get("tipo_fonte") == "negozio" or gruppo.get("classico"):
        a["chiave_mercato"] = None  # senza un modello riconosciuto non c'è un mercato con cui confrontare
    else:
        a["chiave_mercato"] = f"{gruppo['nome']}|{a['tipo']}"

    a["prezzo_eur"] = in_euro(a["prezzo"], a["valuta"], tassi)
    sped = in_euro(a["spedizione"], a["valuta_spedizione"] or a["valuta"], tassi)
    stimata = sped is None
    if stimata:
        sped = gruppo.get("spedizione_stimata_eur", imp.get("spedizione_stimata_eur", 25))
    a["spedizione_eur"] = sped
    a["spedizione_stimata"] = stimata
    if a["prezzo_eur"] is None:
        a["totale_eur"], a["extra_ue"] = None, a["paese"] not in PAESI_UE
    else:
        a["totale_eur"], a["extra_ue"] = arrivo_a_casa(a["prezzo_eur"], sped, a["paese"], imp)

    avvisi = []
    if a["extra_ue"]:
        avvisi.append("fuori UE: IVA e dogana sono una stima, il conto vero è nel checkout")
    if stimata:
        avvisi.append("spedizione non indicata, costo stimato")
    if a["fonte"] == "eBay":
        if a["feedback_n"] is None:
            avvisi.append("venditore senza feedback visibili")
        elif a["feedback_n"] < 10:
            avvisi.append(f"venditore con soli {a['feedback_n']} feedback")
        if a["feedback_pct"] is not None and a["feedback_pct"] < 97:
            avvisi.append(f"feedback positivi al {a['feedback_pct']:.0f}%")
    if a["asta"]:
        avvisi.append("asta: il prezzo mostrato è l'offerta attuale")
    for s in valutatore.sospetto(a["titolo"]):
        avvisi.append(f"il titolo contiene «{s}»")
    a["avvisi"] = avvisi
    return a


def calcola_affari(archivio, cfg):
    av = cfg["avvisi"]
    gruppi = {}
    for a in archivio.values():
        if a.get("totale_eur") and not a.get("asta") and a.get("chiave_mercato"):
            gruppi.setdefault(a["chiave_mercato"], []).append(a["totale_eur"])
    mediane = {k: statistics.median(v) for k, v in gruppi.items() if len(v) >= av["affare_minimo_annunci"]}
    for a in archivio.values():
        a["affare"], a["rapporto_mediana"] = False, None
        m = mediane.get(a.get("chiave_mercato")) if a.get("chiave_mercato") else None
        if m and a.get("totale_eur") and not a.get("asta"):
            rapporto = a["totale_eur"] / m
            a["rapporto_mediana"] = round(rapporto, 2)
            a["mediana_eur"] = round(m, 2)
            if rapporto <= av["affare_sotto_mediana"] and a["totale_eur"] >= av["affare_prezzo_minimo_eur"]:
                a["affare"] = True
    return archivio


def da_avvisare(a, cfg):
    """Restituisce l'elenco dei motivi per cui l'annuncio merita un avviso (vuoto = nessun avviso)."""
    av = cfg["avvisi"]
    motivi = []
    if not a["classico"] and a["punteggio"] >= av["soglia_punteggio"]:
        motivi.append(f"Pezzo particolare, punteggio {a['punteggio']}/10: {', '.join(a['motivi'])}")
    if a.get("ricerca_salvata"):
        motivi.append("Nuovo risultato di una tua ricerca salvata")
    if a["affare"]:
        motivi.append(
            f"Affare: costa il {round(a['rapporto_mediana'] * 100)}% della mediana "
            f"di annunci simili (circa {a['mediana_eur']:.0f} EUR)"
        )
    if not motivi:
        return []
    if a.get("notificato"):
        prima = a.get("prezzo_notificato")
        ribasso = av["riavvisa_se_ribasso"]
        if prima and a.get("totale_eur") and a["totale_eur"] <= prima * (1 - ribasso):
            return ["Prezzo sceso del " + str(round((1 - a["totale_eur"] / prima) * 100)) + "%"] + motivi
        return []
    return motivi


def esegui(cfg, percorso_dati, cerca_ebay, cerca_allegro, telegram, adesso, tassi, scarica_fonte=None, ebay_nota=None, forza=False):
    dati = carica_json(percorso_dati, {"items": []})
    archivio = {a["id"]: a for a in dati.get("items", [])}
    valutatore = Valutatore(cfg)
    gen = cfg["generale"]
    esclusi = set(gen.get("paesi_esclusi", []))
    toccati = []

    def acquisisci(a, gruppo, negozio=False):
        if not a["url"].startswith("https://") or a.get("prezzo") is None:
            return
        if (a["paese"] in esclusi and a["paese"] not in gruppo.get("permetti_paesi", [])) \
                or valutatore.da_scartare(a["titolo"]):
            return
        if negozio:
            if a.get("nuovo") and gruppo.get("escludi_nuovo", True):
                return
            if valutatore.da_scartare_negozio(a["titolo"]):
                return
        if gruppo.get("modalita") == "moderno" and valutatore.da_scartare_moderno(a["titolo"]):
            return
        a = elabora(a, gruppo, valutatore, tassi, cfg)
        if a["modalita"] == "moderno" and a["tipo"] == "altro":
            return  # la modalità moderna mostra solo fotocamere e obiettivi
        if negozio and not gruppo.get("ricerca_salvata") and not gruppo.get("tieni_tutto") and a["tipo"] == "altro" and a["punteggio"] < 1 and not a["motivi"]:
            return
        vecchio = archivio.get(a["id"], {})
        a["primo_visto"] = vecchio.get("primo_visto", iso(adesso))
        a["ultimo_visto"] = adesso.strftime("%Y-%m-%d")
        a["notificato"] = vecchio.get("notificato", False)
        a["prezzo_notificato"] = vecchio.get("prezzo_notificato")
        archivio[a["id"]] = a
        toccati.append(a["id"])

    stato = dict(dati.get("stato_fonti", {}))
    errori, riuscite, ricevuti, ultimo_errore = 0, 0, 0, None
    piano = piano_ricerche(cfg, adesso) if cerca_ebay else []
    for idx, paese, mkt in piano:
        gruppo = cfg["ricerche"][idx]
        try:
            grezzi = cerca_ebay(gruppo["q"], mkt, paese)
        except mod_ebay.ErroreAutEbay as e:
            errori += 1
            ultimo_errore = str(e)
            log.error("eBay non accetta le chiavi, mi fermo: %s", e)
            break
        except Exception as e:  # noqa: BLE001
            errori += 1
            ultimo_errore = str(e)
            log.error("Ricerca fallita (%s, %s): %s", gruppo["nome"], paese, e)
            if (errori >= 5 and not riuscite) or errori >= 15:
                log.error("Troppi errori, mi fermo per questa esecuzione.")
                break
            continue
        riuscite += 1
        ricevuti += len(grezzi)
        for g in grezzi:
            acquisisci(mod_ebay.normalizza_annuncio(g, mkt), gruppo)
    if piano:
        prec = stato.get("eBay", {})
        stato["eBay"] = {"controllato": iso(adesso), "ok": riuscite > 0, "errore": (ultimo_errore or "")[:300] or None,
                         "ultimo_ok": iso(adesso) if riuscite else prec.get("ultimo_ok"), "iniziale": True,
                         "trovati": ricevuti, "ricerche": riuscite, "ricerche_fallite": errori}
    elif ebay_nota:
        stato["eBay"] = {"controllato": iso(adesso), "ok": False, "errore": ebay_nota, "trovati": 0,
                         "ultimo_ok": stato.get("eBay", {}).get("ultimo_ok")}

    if scarica_fonte:
        for f in cfg.get("fonti", []):
            if not f.get("attivo", True):
                continue
            nome = f["nome"]
            prec = stato.get(nome, {})
            if prec.get("controllato") and prec.get("ok", True) and not forza:  # una fonte in errore si riprova a ogni giro
                trascorso = adesso - datetime.strptime(prec["controllato"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                if trascorso < timedelta(minutes=f.get("ogni_minuti", 120)):
                    continue
            try:
                voci, completo = scarica_fonte(f)
            except Exception as e:  # noqa: BLE001
                log.error("Fonte %s non letta: %s", nome, e)
                stato[nome] = {**prec, "controllato": iso(adesso), "ok": False, "errore": str(e)[:200]}
                continue
            gruppo = {"nome": nome, "classico": f.get("classico", False), "escludi_nuovo": f.get("escludi_nuovo", True),
                      "permetti_paesi": f.get("permetti_paesi", []), "modalita": f.get("modalita", "vintage"),
                      "tieni_tutto": f.get("tieni_tutto", cfg.get("negozi", {}).get("tieni_tutto", False)), "ricerca_salvata": f.get("tipo") == "email" or f.get("ricerca_salvata", False),
                      "spedizione_stimata_eur": f.get("spedizione_stimata_eur", cfg["importazione"].get("spedizione_stimata_eur", 25))}
            prima = len(toccati)
            for v in voci:
                acquisisci(v, gruppo, negozio=True)
            nuovi_id = toccati[prima:]
            iniziale = not prec.get("iniziale")
            if iniziale:
                # primo giro su questa fonte: tutto ciò che c'è già non è una novità, niente avvisi
                for id_ in nuovi_id:
                    archivio[id_]["notificato"] = True
                    archivio[id_]["prezzo_notificato"] = archivio[id_]["totale_eur"]
            if completo:
                presenti = {v["id"] for v in voci}
                for id_ in [k for k, a in archivio.items() if a["fonte"] == nome and k not in presenti]:
                    del archivio[id_]
            stato[nome] = {"controllato": iso(adesso), "ultimo_ok": iso(adesso), "ok": True, "errore": None,
                           "iniziale": True, "trovati": len(voci)}
            log.info("Fonte %s: %d prodotti letti, %d rilevanti%s.", nome, len(voci), len(nuovi_id),
                     " (primo giro, nessun avviso)" if iniziale else "")

    if cfg.get("allegro", {}).get("attivo") and cerca_allegro:
        gruppo = {"nome": "Allegro", "classico": False}
        for frase in cfg["allegro"]["frasi"]:
            try:
                for g in cerca_allegro(frase):
                    acquisisci(mod_allegro.normalizza_annuncio(g), gruppo)
            except mod_allegro.AllegroNonAbilitato as e:
                log.warning("%s Salto Allegro.", e)
                break
            except Exception as e:  # noqa: BLE001
                log.error("Allegro fallito (%s): %s", frase, e)

    calcola_affari(archivio, cfg)

    # avvisi
    nuovi = []
    for id_ in dict.fromkeys(toccati):
        a = archivio[id_]
        motivi = da_avvisare(a, cfg)
        if motivi:
            a["motivi_avviso"] = motivi
            nuovi.append(a)
    nuovi.sort(key=lambda a: (a["affare"], a["punteggio"]), reverse=True)
    inviati = 0
    if telegram and nuovi:
        massimo = gen["max_avvisi_per_esecuzione"]
        for a in nuovi[:massimo]:
            try:
                telegram.annuncio(formatta_avviso(a, NOMI_PAESI), a.get("immagine"))
                a["notificato"], a["prezzo_notificato"] = True, a["totale_eur"]
                inviati += 1
            except Exception as e:  # noqa: BLE001
                log.error("Avviso non inviato: %s", e)
        resto = nuovi[massimo:]
        if resto:
            try:
                righe = [f"Altri {len(resto)} annunci da vedere sul sito, non inviati uno per uno:"]
                righe += [f"{a['titolo'][:80]} ({a['totale_eur']:.0f} EUR)" for a in resto[:10]]
                telegram.testo("\n".join(righe))
                for a in resto:
                    a["notificato"], a["prezzo_notificato"] = True, a["totale_eur"]
            except Exception as e:  # noqa: BLE001
                log.error("Riassunto non inviato: %s", e)
    elif nuovi:
        log.info("Avvisi che sarebbero partiti (Telegram non configurato): %d", len(nuovi))
        for a in nuovi:
            log.info("  %s | %s", a["titolo"][:90], " / ".join(a["motivi_avviso"]))

    # pulizia
    limite = (adesso - timedelta(days=gen["conserva_giorni"])).strftime("%Y-%m-%d")
    ora = iso(adesso)
    for id_ in list(archivio):
        a = archivio[id_]
        if a["ultimo_visto"] < limite or (a.get("fine_asta") and a["fine_asta"] < ora):
            del archivio[id_]
    elenco = sorted(archivio.values(), key=lambda a: a["primo_visto"], reverse=True)
    def taglia(voci, massimo):
        if len(voci) <= massimo:
            return voci
        return sorted(voci, key=lambda a: (bool(a.get("affare")), a["punteggio"], a["primo_visto"]), reverse=True)[:massimo]
    # tagli separati: la marea di annunci eBay non deve spingere fuori i negozi (e far ripartire i loro avvisi)
    elenco = taglia([a for a in elenco if a["fonte"] == "eBay"], MAX_ARCHIVIO) + \
        taglia([a for a in elenco if a["fonte"] != "eBay"], MAX_ARCHIVIO_NEGOZI)
    elenco.sort(key=lambda a: a["primo_visto"], reverse=True)

    for a in elenco:
        a.pop("motivi_avviso", None)

    configurate = {f["nome"] for f in cfg.get("fonti", [])} | {"eBay"}
    uscita = {
        "aggiornato": iso(adesso),
        "nomi_paesi": NOMI_PAESI,
        "stato_fonti": {k: v for k, v in stato.items() if k in configurate},
        "items": elenco,
    }
    Path(percorso_dati).parent.mkdir(parents=True, exist_ok=True)
    Path(percorso_dati).write_text(json.dumps(uscita, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log.info("Fatto: %d annunci in archivio, %d toccati, %d avvisi inviati, %d errori.",
             len(elenco), len(set(toccati)), inviati, errori)
    return uscita


def main(argv=None):
    ap = argparse.ArgumentParser(prog="cacciatore")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--dati", default="docs/data/items.json")
    ap.add_argument("--fixture", help="file JSON con annunci eBay di prova, senza chiamare eBay")
    ap.add_argument("--senza-telegram", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    adesso = datetime.now(timezone.utc)
    ebay_nota = None

    if args.fixture:
        grezzi = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
        usati = {"fatto": False}

        def cerca_ebay(q, mkt, paese):
            if usati["fatto"]:
                return []
            usati["fatto"] = True
            return grezzi

        cerca_allegro = None
        tassi = {"EUR": 1.0, "USD": 1.15, "GBP": 0.86, "JPY": 170.0, "PLN": 4.25, "RON": 5.1}
    else:
        cid, sec = os.environ.get("EBAY_CLIENT_ID"), os.environ.get("EBAY_CLIENT_SECRET")
        gen = cfg["generale"]
        cerca_ebay = None
        if cid and sec:
            client = mod_ebay.Ebay(cid, sec)

            def cerca_ebay(q, mkt, paese):
                return client.cerca(q, mkt, paese, gen.get("consegna_in"), gen.get("categoria_ebay") or None,
                                    gen.get("risultati_per_chiamata", 50))
        else:
            log.warning("Mancano EBAY_CLIENT_ID e EBAY_CLIENT_SECRET: salto eBay, leggo solo le altre fonti.")
            ebay_nota = ("mancano i secret EBAY_CLIENT_ID ed EBAY_CLIENT_SECRET: devono stare in Secrets and variables, "
                         "scheda Secrets, con questi nomi esatti")

        cerca_allegro = None
        if os.environ.get("ALLEGRO_CLIENT_ID") and os.environ.get("ALLEGRO_CLIENT_SECRET"):
            al = mod_allegro.Allegro(os.environ["ALLEGRO_CLIENT_ID"], os.environ["ALLEGRO_CLIENT_SECRET"])
            cerca_allegro = al.cerca
        tassi = scarica_tassi()

    telegram = None
    if not args.senza_telegram and os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"):
        telegram = Telegram(os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_ID"])

    scarica_fonte = None
    if not args.fixture:
        rete = Rete(pausa=cfg.get("negozi", {}).get("pausa_secondi", 2.0))

        def scarica_fonte(f):
            return mod_negozi.scarica(f, rete)

    esegui(cfg, args.dati, cerca_ebay, cerca_allegro, telegram, adesso, tassi, scarica_fonte, ebay_nota, forza=bool(os.environ.get("CACCIATORE_FORZA")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
