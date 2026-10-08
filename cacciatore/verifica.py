"""Prova a secco delle fonti in config.yaml: non salva niente e non manda avvisi.

    python -m cacciatore.verifica            tutte le fonti
    python -m cacciatore.verifica "Nome"     solo quella

Per ogni fonte dice se robots.txt permette la lettura, se la pagina risponde, quanti prodotti legge e
quanti restano dopo i filtri. Serve a controllare un sito nuovo prima di lasciarlo girare da solo.
"""
import argparse
import os
import sys
from pathlib import Path

import yaml

from . import negozi
from .ebay import Ebay
from .main import PAESI_UE
from .punteggio import Valutatore
from .rete import ErroreRete, Rete, Vietato


def controlla(fonte, cfg, rete):
    esito = {"nome": fonte["nome"], "tipo": fonte.get("tipo"), "url": fonte.get("url"), "ok": False,
             "robots": None, "letti": 0, "rilevanti": 0, "esempi": [], "nota": ""}
    base = (fonte.get("url") or "").rstrip("/")
    if fonte.get("tipo") not in ("etsy", "email"):  # API ufficiale e posta: nessun robots.txt di mezzo
        try:
            esito["robots"] = rete.permesso(base + "/")
        except Exception as e:  # noqa: BLE001
            esito["nota"] = f"robots.txt non letto: {e}"
            return esito
    try:
        voci, completo = negozi.scarica(fonte, rete)
    except Vietato:
        motivo = getattr(rete, "motivo_robots", {}).get(base)
        esito["nota"] = (f"fonte non usabile: {motivo}" if motivo
                         else "robots.txt vieta la lettura di queste pagine: la fonte non può essere usata")
        esito["robots"] = False
        return esito
    except (ErroreRete, ValueError, KeyError) as e:
        esito["nota"] = f"lettura fallita: {e}"
        return esito
    except ImportError as e:
        esito["nota"] = f"manca una libreria: {e}"
        return esito
    esito["ok"] = True
    esito["letti"] = len(voci)
    if not voci:
        esito["nota"] = "pagina letta ma nessun prodotto: controlla l'indirizzo, o i selettori per il tipo html"
        return esito
    val = Valutatore(cfg)
    esclusi = set(cfg["generale"].get("paesi_esclusi", []))
    rilevanti = []
    for v in voci:
        if (v["paese"] in esclusi and v["paese"] not in fonte.get("permetti_paesi", [])) or val.da_scartare(v["titolo"]) or val.da_scartare_negozio(v["titolo"]):
            continue
        if v.get("nuovo") and fonte.get("escludi_nuovo", True):
            continue
        punteggio, _, _ = val.valuta(v["titolo"])
        if punteggio < 1 and fonte.get("tipo") != "email" and not cfg.get("negozi", {}).get("tieni_tutto", False):
            continue
        rilevanti.append((punteggio, v))
    rilevanti.sort(key=lambda x: -x[0])
    esito["rilevanti"] = len(rilevanti)
    esito["esempi"] = [f"{p:.0f}/10  {v['titolo'][:70]}  {v['prezzo']:.0f} {v['valuta']}" for p, v in rilevanti[:5]]
    if fonte.get("paese") not in PAESI_UE:
        esito["nota"] = "paese fuori UE: il totale a casa include una stima di IVA e dogana"
    if not completo:
        esito["nota"] = (esito["nota"] + " " if esito["nota"] else "") + \
            "elenco troncato dal limite di pagine: i venduti non verranno rimossi"
    return esito


def diagnosi_chiavi(cid, sec):
    """Forma delle chiavi, senza rivelarle: basta a riconoscere sandbox, valori scambiati, spazi o a capo."""
    def forma(v):
        return f"{len(v)} caratteri" + (", con spazi o a capo ai margini" if v != v.strip() else "") + \
               (", con virgolette" if v.strip()[:1] in "\"'" and v.strip() else "")
    amb = "Production" if "-PRD-" in cid.upper() else ("SANDBOX" if "-SBX-" in cid.upper() else "non riconoscibile")
    return (f"App ID: {forma(cid)}, ambiente {amb}, inizia con «{cid.strip()[:4]}». "
            f"Cert ID: {forma(sec)}, inizia con «{sec.strip()[:4]}» (in Production comincia con PRD-). "
            f"Se Client ID e Secret sono uguali o il Secret non comincia con PRD-, sono scambiati o è il Dev ID.")


def controlla_ebay(prova=None):
    """Una chiamata vera a eBay: dice se le chiavi funzionano e, se no, riporta la risposta di eBay parola per parola."""
    esito = {"nome": "eBay", "tipo": "api", "url": "", "ok": False, "robots": None, "letti": 0, "rilevanti": 0,
             "esempi": [], "nota": ""}
    cid, sec = os.environ.get("EBAY_CLIENT_ID", "").strip(), os.environ.get("EBAY_CLIENT_SECRET", "").strip()
    if not (cid and sec):
        esito["nota"] = "i secret EBAY_CLIENT_ID ed EBAY_CLIENT_SECRET non arrivano al programma (nome sbagliato o messi nella scheda Variables)"
        return esito
    esito["diagnosi"] = diagnosi_chiavi(os.environ.get("EBAY_CLIENT_ID", ""), os.environ.get("EBAY_CLIENT_SECRET", ""))
    try:
        r = prova() if prova else Ebay(cid, sec).prova()
    except Exception as e:  # noqa: BLE001
        esito["nota"] = f"eBay non raggiungibile: {e}"
        return esito
    if r["token"] != 200:
        esito["nota"] = f"token rifiutato ({r['token']}): {r['token_testo']}. {esito['diagnosi']}"
    elif r.get("ricerca") != 200:
        esito["nota"] = f"token ok, ricerca rifiutata ({r.get('ricerca')}): {r.get('ricerca_testo')}"
    else:
        esito["ok"] = True
        esito["letti"] = r.get("totale") or 0
        esito["esempi"] = r.get("esempi", [])
        esito["nota"] = "chiavi accettate, la ricerca risponde"
    return esito


def testo(esiti):
    righe = []
    for e in esiti:
        stato = "ok" if e["ok"] else "NON FUNZIONA"
        righe.append(f"{e['nome']} ({e['tipo']}): {stato}")
        if e["robots"] is None:
            righe.append("  robots.txt: non si applica (API ufficiale o posta)")
        else:
            righe.append(f"  robots.txt: {'permette' if e['robots'] else 'vieta o non raggiungibile'}")
        if e["ok"]:
            righe.append(f"  prodotti letti: {e['letti']}, rilevanti dopo i filtri: {e['rilevanti']}")
            for x in e["esempi"]:
                righe.append(f"    {x}")
        if e["nota"]:
            righe.append(f"  {e['nota']}")
        righe.append("")
    return "\n".join(righe)


def markdown(esiti):
    righe = ["| Fonte | Esito | Letti | Rilevanti | Note |", "|---|---|---|---|---|"]
    for e in esiti:
        righe.append(f"| {e['nome']} | {'ok' if e['ok'] else 'non funziona'} | {e['letti']} | {e['rilevanti']} | {e['nota']} |")
    for e in esiti:
        if e["esempi"]:
            righe += ["", f"{e['nome']}, i primi risultati:", ""] + [f"- {x}" for x in e["esempi"]]
    return "\n".join(righe) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="cacciatore.verifica")
    ap.add_argument("nome", nargs="?", help="nome di una sola fonte")
    ap.add_argument("--config", default=str(Path(__file__).parent.parent / "config.yaml"))
    args = ap.parse_args(argv)
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    fonti = [f for f in cfg.get("fonti", []) if not args.nome or f["nome"].lower() == args.nome.lower()]
    solo_ebay = bool(args.nome) and args.nome.lower() == "ebay"
    if not fonti and not solo_ebay:
        print("Nessuna fonte da controllare.")
        return 1
    rete = Rete(pausa=cfg.get("negozi", {}).get("pausa_secondi", 2.0))
    esiti = [controlla_ebay()] if (solo_ebay or not args.nome) else []
    esiti += [controlla(f, cfg, rete) for f in fonti if f.get("attivo", True) or args.nome]
    print(testo(esiti))
    riassunto = os.environ.get("GITHUB_STEP_SUMMARY")
    if riassunto:
        with open(riassunto, "a", encoding="utf-8") as f:
            f.write(markdown(esiti))
    return 0 if all(e["ok"] for e in esiti) else 2


if __name__ == "__main__":
    sys.exit(main())
