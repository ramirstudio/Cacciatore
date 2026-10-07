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
        esito["nota"] = "robots.txt vieta la lettura oppure il sito non è raggiungibile da qui: la fonte non può essere usata"
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
        if punteggio < 1 and fonte.get("tipo") != "email":
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
    if not fonti:
        print("Nessuna fonte da controllare.")
        return 1
    rete = Rete(pausa=cfg.get("negozi", {}).get("pausa_secondi", 2.0))
    esiti = [controlla(f, cfg, rete) for f in fonti]
    print(testo(esiti))
    riassunto = os.environ.get("GITHUB_STEP_SUMMARY")
    if riassunto:
        with open(riassunto, "a", encoding="utf-8") as f:
            f.write(markdown(esiti))
    return 0 if all(e["ok"] for e in esiti) else 2


if __name__ == "__main__":
    sys.exit(main())
