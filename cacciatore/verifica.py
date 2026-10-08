name: verifica fonti

on:
  workflow_dispatch:

jobs:
  verifica:
    runs-on: ubuntu-latest
    timeout-minutes: 40
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install -r requirements.txt
      - name: Prova delle fonti
        env:
          EBAY_CLIENT_ID: ${{ secrets.EBAY_CLIENT_ID }}
          EBAY_CLIENT_SECRET: ${{ secrets.EBAY_CLIENT_SECRET }}
          ETSY_API_KEY: ${{ secrets.ETSY_API_KEY }}
          ETSY_API_SECRET: ${{ secrets.ETSY_API_SECRET }}
          EMAIL_IMAP_UTENTE: ${{ secrets.EMAIL_IMAP_UTENTE }}
          EMAIL_IMAP_PASSWORD: ${{ secrets.EMAIL_IMAP_PASSWORD }}
        run: python -m cacciatore.verifica
