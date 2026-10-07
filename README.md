Cacciatore cerca ogni mezz'ora annunci eBay, e ogni due ore i cataloghi di alcuni negozi di usato, di fotocamere, ottiche e accessori particolari o molto convenienti, li valuta e manda un messaggio Telegram per ognuno che passa la soglia. Lo storico si sfoglia da un sito su GitHub Pages.

Le istruzioni complete sono nel manuale PDF. In breve: carica questa cartella in un repository pubblico GitHub, inserisci i cinque segreti elencati sotto in Settings > Secrets and variables > Actions, attiva GitHub Pages dalla cartella /docs del ramo main, poi lancia il workflow "cerca" a mano la prima volta dalla scheda Actions.

Segreti richiesti: EBAY_CLIENT_ID, EBAY_CLIENT_SECRET, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID. Facoltativi: ALLEGRO_CLIENT_ID, ALLEGRO_CLIENT_SECRET.

Prova locale senza chiamare eBay né Telegram:

    pip install -r requirements.txt
    python -m cacciatore --fixture tests/fixtures/ebay_sample.json --dati /tmp/prova/items.json --senza-telegram
    python -m unittest discover -s tests

I negozi si elencano in config.yaml sotto fonti (Shopify, WooCommerce, schema.org, RSS, HTML). Il workflow "verifica fonti" prova ogni sito senza salvare nulla: robots.txt viene sempre rispettato, e alla prima lettura di una fonte nuova non partono avvisi.

    python -m cacciatore.verifica

Tutto il comportamento si regola da config.yaml: paesi, gruppi di ricerca, pesi del punteggio, soglie degli avvisi.
