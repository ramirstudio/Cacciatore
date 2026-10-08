"""Lettore da casa.

Alcuni negozi (MPB) rifiutano le richieste che partono dai server di GitHub, anche se il loro robots.txt
permette di leggere le pagine di categoria. Questo programma gira sul PC di casa, legge solo le fonti
con `da_casa: true` in config.yaml, con lo stesso nome dichiarato (CacciatoreBot), le stesse pause e lo
stesso rispetto di robots.txt, e deposita il risultato in docs/data/casa/ nel repository.
Il giro su GitHub poi lo tratta come qualsiasi altra fonte.

    python -m cacciatore.casa --token-file token.txt          lettura e invio
    python -m cacciatore.casa --prova                          solo lettura, stampa cosa trova
"""
import argparse
import base64
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

import requests
import yaml

from . import negozi as mod_negozi
from .rete import Rete

log = logging.getLogger("cacciatore.casa")
REPO = "ramirstudio/Cacciatore"


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def leggi(cfg, rete, solo=None, campione=None):
    risultati = []
    for f in cfg.get("fonti", []):
        if not f.get("da_casa") or not f.get("attivo", True):
            continue
        if solo and solo.lower() not in f["nome"].lower():
            continue
        fonte = {k: v for k, v in f.items() if k != "da_casa"}
        inizio = time.monotonic()
        try:
            voci, completo = mod_negozi.scarica(fonte, rete)
            if not voci:
                raise RuntimeError("nessun prodotto riconosciuto nelle pagine: forse il sito ha cambiato struttura")
            ris = {"nome": f["nome"], "letto": iso(datetime.now(timezone.utc)), "ok": True, "errore": None,
                   "completo": completo, "voci": voci}
            log.info("%s: %d prodotti in %.0f s", f["nome"], len(voci), time.monotonic() - inizio)
        except Exception as e:  # noqa: BLE001
            motivo = next(iter(rete.motivo_robots.values()), None)
            errore = motivo or str(e)
            ris = {"nome": f["nome"], "letto": iso(datetime.now(timezone.utc)), "ok": False, "errore": errore[:300],
                   "completo": False, "voci": []}
            log.error("%s non letto: %s", f["nome"], errore)
        risultati.append(ris)
    if campione and risultati:
        # una pagina grezza, per controllare a mano come il sito presenta i prodotti
        primo = next(f for f in cfg["fonti"] if f["nome"] == risultati[0]["nome"])
        try:
            r = rete.get(primo["urls"][0])
            with open(campione, "w", encoding="utf-8") as fh:
                fh.write(r.text)
        except Exception as e:  # noqa: BLE001
            log.warning("Campione non salvato: %s", e)
    return risultati


def invia(ris, token, repo=REPO):
    percorso = mod_negozi.file_casa(ris["nome"]).replace(os.sep, "/")
    url = f"https://api.github.com/repos/{repo}/contents/{percorso}"
    intest = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
              "X-GitHub-Api-Version": "2022-11-28"}
    contenuto = base64.b64encode(json.dumps(ris, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).decode()
    for tentativo in range(3):
        r = requests.get(url, headers=intest, timeout=30)
        if r.status_code == 401:
            raise RuntimeError("GitHub rifiuta il token: controlla token.txt (scaduto o copiato male)")
        corpo = {"message": f"casa: {ris['nome']}", "content": contenuto,
                 "committer": {"name": "cacciatore-casa", "email": "cacciatore@users.noreply.github.com"}}
        if r.status_code == 200:
            corpo["sha"] = r.json()["sha"]
        r = requests.put(url, headers=intest, json=corpo, timeout=60)
        if r.status_code in (200, 201):
            return
        if r.status_code in (403, 404):
            raise RuntimeError(f"GitHub {r.status_code}: il token non ha il permesso Contents in scrittura su {repo}")
        if r.status_code not in (409, 422):
            r.raise_for_status()
        time.sleep(5 * (tentativo + 1))  # il giro su GitHub ha appena scritto: riprovo con lo sha nuovo
    raise RuntimeError("GitHub non accetta il file dopo 3 tentativi")


def main(argv=None):
    p = argparse.ArgumentParser(description="Legge dal PC di casa le fonti bloccate per GitHub (MPB).")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--token-file", help="file con il token GitHub (permesso Contents in scrittura)")
    p.add_argument("--repo", default=REPO)
    p.add_argument("--prova", action="store_true", help="legge e stampa, senza inviare nulla")
    p.add_argument("--solo", help="legge solo le fonti il cui nome contiene questo testo")
    p.add_argument("--campione", help="salva qui l'HTML grezzo della prima pagina letta")
    p.add_argument("--log", help="scrive il registro anche in questo file")
    args = p.parse_args(argv)
    try:  # la console di Windows non conosce tutti i caratteri dei titoli
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass

    gestori = [logging.StreamHandler(sys.stdout)]
    if args.log:
        gestori.append(logging.FileHandler(args.log, encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M", handlers=gestori)

    with open(args.config, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    os.environ.setdefault("CACCIATORE_CONTATTO", "https://ramirstudio.github.io/Cacciatore/")
    rete = Rete(pausa=max(3.0, cfg.get("negozi", {}).get("pausa_secondi", 2.0)))
    risultati = leggi(cfg, rete, args.solo, args.campione)
    if not risultati:
        log.warning("Nessuna fonte con da_casa: true in %s", args.config)
        return 1

    if args.prova:
        for ris in risultati:
            print(f"\n{ris['nome']}: {'OK' if ris['ok'] else 'ERRORE'} - {len(ris['voci'])} prodotti")
            if ris["errore"]:
                print("  ", ris["errore"])
            for v in ris["voci"][:15]:
                print(f"   {v['prezzo']:>9} {v['valuta']}  {v['titolo'][:70]}")
        return 0

    if not args.token_file or not os.path.exists(args.token_file):
        log.error("Manca il file del token GitHub (%s)", args.token_file)
        return 2
    with open(args.token_file, encoding="utf-8") as fh:
        token = fh.read().strip()
    falliti = 0
    for ris in risultati:
        try:
            invia(ris, token, args.repo)
            log.info("%s inviato a GitHub", ris["nome"])
        except Exception as e:  # noqa: BLE001
            falliti += 1
            log.error("%s non inviato: %s", ris["nome"], e)
    return 1 if falliti else 0


if __name__ == "__main__":
    sys.exit(main())
