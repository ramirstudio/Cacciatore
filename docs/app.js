(function () {
  "use strict";

  var CHIAVE_PREF = "cacciatore.preferiti";
  var CHIAVE_NASC = "cacciatore.nascosti";
  var dati = { items: [], nomi_paesi: {} };

  function leggi(chiave) {
    try { return JSON.parse(localStorage.getItem(chiave) || "[]"); } catch (e) { return []; }
  }
  function scrivi(chiave, valore) {
    try { localStorage.setItem(chiave, JSON.stringify(valore)); } catch (e) { /* storage non disponibile */ }
  }
  var preferiti = new Set(leggi(CHIAVE_PREF));
  var nascosti = new Set(leggi(CHIAVE_NASC));

  var el = {};
  ["stato", "tema", "v-elenco", "v-griglia", "m-vintage", "m-moderno", "n-vintage", "n-moderno", "fonti", "elenco-fonti", "elenco", "vuoto", "conteggio", "pannello", "f-testo", "f-tipo", "f-marca", "f-paese", "f-fonte", "f-rarita",
   "f-max", "f-ordine", "f-affari", "f-nofuoriue", "f-solopreferiti", "f-nascosti"]
    .forEach(function (id) { el[id] = document.getElementById(id); });

  function euro(x) {
    return new Intl.NumberFormat("it-IT", { style: "currency", currency: "EUR", maximumFractionDigits: 0 }).format(x);
  }
  function fa(iso) {
    var min = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
    if (min < 60) return min + " min fa";
    var ore = Math.round(min / 60);
    if (ore < 48) return ore + " h fa";
    return Math.round(ore / 24) + " giorni fa";
  }
  var PAESI_BASE = { FI: "Finlandia", SE: "Svezia", DK: "Danimarca", IE: "Irlanda", PT: "Portogallo", LU: "Lussemburgo",
    CH: "Svizzera", NO: "Norvegia", TR: "Turchia", KR: "Corea del Sud", TW: "Taiwan", CA: "Canada", AU: "Australia",
    ID: "Indonesia", ZA: "Sudafrica", VN: "Vietnam", TH: "Thailandia", MY: "Malesia", SG: "Singapore", PH: "Filippine",
    NZ: "Nuova Zelanda", ES: "Spagna", FR: "Francia", PT: "Portogallo", NL: "Paesi Bassi", BE: "Belgio", RS: "Serbia", US: "Stati Uniti",
    MD: "Moldavia", UA: "Ucraina", IS: "Islanda", CY: "Cipro", MT: "Malta", BA: "Bosnia ed Erzegovina", ME: "Montenegro",
    MK: "Macedonia del Nord", AL: "Albania", LI: "Liechtenstein", HU: "Ungheria", BG: "Bulgaria", RO: "Romania", PL: "Polonia",
    SK: "Slovacchia", CZ: "Cechia", EE: "Estonia", LV: "Lettonia", LT: "Lituania", HR: "Croazia", SI: "Slovenia", GR: "Grecia" };
  function paese(codice) { return dati.nomi_paesi[codice] || PAESI_BASE[codice] || codice || "paese non indicato"; }

  var MARCHE = [
    ["Canon", /\b(canon|eos)\b/], ["Nikon", /\b(nikon|nikkor)\b/], ["Sony", /\b(sony|alpha|ilce)\b/],
    ["Fujifilm", /\b(fujifilm|fuji|fujinon)\b/], ["Panasonic", /\b(panasonic|lumix)\b/],
    ["Olympus / OM System", /\b(olympus|om system|zuiko)\b/], ["Pentax / Ricoh", /\b(pentax|ricoh)\b/],
    ["Leica", /\bleica\b/], ["Sigma", /\bsigma\b/], ["Tamron", /\btamron\b/], ["Tokina", /\btokina\b/],
    ["Samyang / Rokinon", /\b(samyang|rokinon)\b/], ["Viltrox", /\bviltrox\b/], ["Zeiss", /\bzeiss\b/],
    ["Voigtländer", /\bvoigtl(ä|a|ae)nder\b/], ["Hasselblad", /\bhasselblad\b/], ["Laowa", /\blaowa\b/],
    ["TTArtisan", /\bttartisan\b/], ["7Artisans", /\b7artisans\b/], ["Yongnuo", /\byongnuo\b/],
    ["Meike", /\bmeike\b/], ["Blackmagic", /\bblackmagic\b/], ["GoPro", /\bgopro\b/], ["DJI", /\bdji\b/]
  ];
  function marcaDi(a) {
    if (a._marca === undefined) {
      var t = (a.titolo || "").toLowerCase();
      a._marca = "Altre";
      for (var i = 0; i < MARCHE.length; i++) { if (MARCHE[i][1].test(t)) { a._marca = MARCHE[i][0]; break; } }
    }
    return a._marca;
  }
  function popolaMarche() {
    if (!dati || !dati.items) return;
    var scelta = el["f-marca"].value, conteggio = {};
    dati.items.forEach(function (a) { if (inModalita(a)) conteggio[marcaDi(a)] = (conteggio[marcaDi(a)] || 0) + 1; });
    el["f-marca"].textContent = "";
    var tutte = document.createElement("option");
    tutte.value = ""; tutte.textContent = "Tutte";
    el["f-marca"].appendChild(tutte);
    Object.keys(conteggio).sort(function (x, y) {
      if (x === "Altre") return 1;
      if (y === "Altre") return -1;
      return conteggio[y] - conteggio[x];
    }).forEach(function (m) {
      var o = document.createElement("option");
      o.value = m; o.textContent = m + " (" + conteggio[m] + ")";
      el["f-marca"].appendChild(o);
    });
    el["f-marca"].value = conteggio[scelta] ? scelta : "";
  }

  function popolaPaesi() {
    var presenti = {};
    dati.items.forEach(function (a) { if (a.paese) presenti[a.paese] = true; });
    Object.keys(presenti).sort(function (a, b) { return paese(a).localeCompare(paese(b), "it"); })
      .forEach(function (c) {
        var o = document.createElement("option");
        o.value = c; o.textContent = paese(c);
        el["f-paese"].appendChild(o);
      });
  }

  function popolaFonti() {
    var conteggio = {};
    dati.items.forEach(function (a) { if (a.fonte) conteggio[a.fonte] = (conteggio[a.fonte] || 0) + 1; });
    Object.keys(conteggio).sort(function (a, b) { return a.localeCompare(b, "it"); }).forEach(function (f) {
      var o = document.createElement("option");
      o.value = f; o.textContent = f + " (" + conteggio[f] + ")";
      el["f-fonte"].appendChild(o);
    });
    var stato = dati.stato_fonti || {};
    var nomi = Object.keys(stato);
    el["elenco-fonti"].textContent = "";
    el.fonti.hidden = nomi.length === 0;
    nomi.forEach(function (n) {
      var s = stato[n];
      var li = nodo("li", s.ok ? "" : "guasta");
      li.appendChild(nodo("strong", null, n));
      var riga = s.ok
        ? s.trovati + (n === "eBay" ? " annunci ricevuti nell'ultimo giro, " : " prodotti letti, ") + (conteggio[n] || 0) + " in elenco, controllata " + fa(s.controllato)
        : "non leggibile: " + (s.errore || "errore sconosciuto") + (s.ultimo_ok ? ". Ultima lettura riuscita " + fa(s.ultimo_ok) : "");
      if (s.ok && s.errore && n === "eBay") riga += ". Alcune ricerche in errore: " + s.errore;
      li.appendChild(nodo("span", "meta", riga));
      el["elenco-fonti"].appendChild(li);
    });
  }

  var GRUPPI_MODERNI = [];
  var CHIAVE_MOD = "cacciatore.modalita";
  var modalita = "vintage";
  function modalitaDi(a) { return a.modalita || (GRUPPI_MODERNI.indexOf(a.gruppo) >= 0 ? "moderno" : "vintage"); }
  function inModalita(a) { var m = modalitaDi(a); return m === "entrambe" || m === modalita; }
  function impostaModalita(m, cambiaOrdine) {
    modalita = m;
    el["m-vintage"].setAttribute("aria-pressed", m === "vintage");
    el["m-moderno"].setAttribute("aria-pressed", m === "moderno");
    salvaTesto(CHIAVE_MOD, m);
    popolaMarche();
    if (cambiaOrdine) el["f-ordine"].value = m === "moderno" ? "affare" : "novita";  // nel moderno conta il prezzo
  }
  function conteggiModalita() {
    var v = 0, mo = 0;
    dati.items.forEach(function (a) { var m = modalitaDi(a); if (m !== "moderno") v++; if (m !== "vintage") mo++; });
    el["n-vintage"].textContent = v; el["n-moderno"].textContent = mo;
    el["m-vintage"].hidden = v === 0;  // senza annunci vintage la scheda sparisce
    if (v === 0 && modalita === "vintage") impostaModalita("moderno", false);
  }

  function filtra() {
    var testo = el["f-testo"].value.trim().toLowerCase();
    var tipo = el["f-tipo"].value, marca = el["f-marca"].value, cod = el["f-paese"].value, fonte = el["f-fonte"].value;
    var rar = parseInt(el["f-rarita"].value, 10) || 0;
    var max = parseFloat(el["f-max"].value);
    var affari = el["f-affari"].checked, soloUE = el["f-nofuoriue"].checked;
    var soloPref = el["f-solopreferiti"].checked, conNasc = el["f-nascosti"].checked;

    var lista = dati.items.filter(function (a) {
      if (!inModalita(a)) return false;
      if (!conNasc && nascosti.has(a.id)) return false;
      if (soloPref && !preferiti.has(a.id)) return false;
      if (testo && a.titolo.toLowerCase().indexOf(testo) === -1) return false;
      if (tipo && a.tipo !== tipo) return false;
      if (marca && marcaDi(a) !== marca) return false;
      if (cod && a.paese !== cod) return false;
      if (fonte && a.fonte !== fonte) return false;
      if (a.punteggio < rar) return false;
      if (!isNaN(max) && a.totale_eur != null && a.totale_eur > max) return false;
      if (affari && !a.affare) return false;
      if (soloUE && a.extra_ue) return false;
      return true;
    });

    var ordine = el["f-ordine"].value;
    lista.sort(function (a, b) {
      if (ordine === "rarita") return b.punteggio - a.punteggio || cmpNovita(a, b);
      if (ordine === "prezzo") return (a.totale_eur == null) - (b.totale_eur == null) || a.totale_eur - b.totale_eur;
      if (ordine === "affare") return (a.rapporto_mediana == null) - (b.rapporto_mediana == null) || a.rapporto_mediana - b.rapporto_mediana;
      return cmpNovita(a, b);
    });
    return lista;
  }
  function cmpNovita(a, b) { return a.primo_visto < b.primo_visto ? 1 : -1; }

  function nodo(tag, classe, testo) {
    var n = document.createElement(tag);
    if (classe) n.className = classe;
    if (testo != null) n.textContent = testo;
    return n;
  }

  function riga(a) {
    var li = nodo("li", "riga" + (nascosti.has(a.id) ? " nascosto" : ""));
    var img = nodo("img", "foto");
    img.alt = ""; img.loading = "lazy"; img.referrerPolicy = "no-referrer";
    if (a.immagine && a.immagine.indexOf("https://") === 0) img.src = a.immagine;
    li.appendChild(img);

    var c = nodo("div");
    var t = nodo("a", "titolo", a.titolo);
    t.href = a.url; t.target = "_blank"; t.rel = "noopener noreferrer";
    c.appendChild(t);

    var p = nodo("div", "prezzo");
    if (a.totale_eur != null) {
      p.appendChild(document.createTextNode(euro(a.totale_eur)));
      var piccolo = nodo("small", null, a.extra_ue ? "  stimato a casa, con IVA e dogana" : "  con spedizione");
      p.appendChild(piccolo);
    } else {
      p.textContent = "Prezzo non disponibile";
    }
    c.appendChild(p);

    var dettagli = [];
    if (a.prezzo_eur != null) {
      dettagli.push((a.asta ? "offerta attuale " : "oggetto ") + euro(a.prezzo_eur) +
        (a.spedizione_eur != null ? ", spedizione " + euro(a.spedizione_eur) + (a.spedizione_stimata ? " (stimata)" : "") : ""));
    }
    dettagli.push(paese(a.paese));
    dettagli.push(a.fonte);
    dettagli.push(fa(a.primo_visto));
    c.appendChild(nodo("div", "meta", dettagli.join(" · ")));

    if (a.punteggio >= 1) {
      var r = nodo("div", "meta");
      var s = nodo("span", "rarita", "Rarità " + a.punteggio + "/10");
      r.appendChild(s);
      if (a.motivi && a.motivi.length) r.appendChild(document.createTextNode(" · " + a.motivi.join(", ")));
      c.appendChild(r);
    }
    if (a.affare) {
      c.appendChild(nodo("div", "meta affare",
        "Affare: " + Math.round(a.rapporto_mediana * 100) + "% della mediana di annunci simili (circa " + euro(a.mediana_eur) + ")"));
    }
    if (a.avvisi && a.avvisi.length) c.appendChild(nodo("div", "attenzione", a.avvisi.join("; ").replace(/^./, function (m) { return m.toUpperCase(); }) + "."));

    var az = nodo("div", "azioni");
    var pref = nodo("button", null, preferiti.has(a.id) ? "Nei preferiti" : "Salva");
    pref.type = "button"; pref.setAttribute("aria-pressed", preferiti.has(a.id));
    pref.onclick = function () { alterna(preferiti, a.id, CHIAVE_PREF); disegna(); };
    var nasc = nodo("button", null, nascosti.has(a.id) ? "Mostra di nuovo" : "Nascondi");
    nasc.type = "button";
    nasc.onclick = function () { alterna(nascosti, a.id, CHIAVE_NASC); disegna(); };
    az.appendChild(pref); az.appendChild(nasc);
    c.appendChild(az);

    li.appendChild(c);
    return li;
  }

  function alterna(insieme, id, chiave) {
    if (insieme.has(id)) insieme.delete(id); else insieme.add(id);
    scrivi(chiave, Array.from(insieme));
  }

  var PASSO = 200, mostrati = 0, listaCorrente = [], sentinella = null, osservatore = null;
  function ridisegna() { disegna(); }

  function aggiornaConteggio() {
    var n = listaCorrente.length;
    el.conteggio.textContent = n + (n === 1 ? " annuncio" : " annunci") +
      (n > mostrati ? ", mostrati " + mostrati : "");
  }

  // aggiunge le righe successive senza ridisegnare l'elenco: la posizione di scorrimento non salta
  function mostraAltri() {
    if (mostrati >= listaCorrente.length) return;
    var frammento = document.createDocumentFragment();
    listaCorrente.slice(mostrati, mostrati + PASSO).forEach(function (a) { frammento.appendChild(riga(a)); });
    mostrati = Math.min(mostrati + PASSO, listaCorrente.length);
    if (sentinella) sentinella.remove();
    el.elenco.appendChild(frammento);
    if (mostrati < listaCorrente.length) el.elenco.appendChild(sentinella);
    else if (osservatore) osservatore.disconnect();
    aggiornaConteggio();
  }

  function preparaSentinella() {
    if (osservatore) osservatore.disconnect();
    sentinella = document.createElement("li");
    sentinella.className = "altri";
    var b = document.createElement("button");
    b.type = "button";
    b.textContent = "Mostra altri";
    b.addEventListener("click", mostraAltri);  // ripiego se il browser non osserva lo scorrimento
    sentinella.appendChild(b);
    if ("IntersectionObserver" in window) {
      osservatore = new IntersectionObserver(function (voci) {
        if (voci.some(function (v) { return v.isIntersecting; })) {
          osservatore.disconnect();
          mostraAltri();
          if (sentinella.isConnected) osservatore.observe(sentinella);
        }
      }, { rootMargin: "600px 0px" });
    }
  }

  function disegna() {
    listaCorrente = filtra();
    el.elenco.textContent = "";
    mostrati = 0;
    preparaSentinella();
    mostraAltri();
    if (osservatore && sentinella.isConnected) osservatore.observe(sentinella);
    var lista = listaCorrente;
    var vuoto = lista.length === 0;
    el.vuoto.hidden = !vuoto;
    if (vuoto) {
      el.vuoto.textContent = dati.items.length === 0
        ? "Nessun annuncio ancora. La prima ricerca parte entro mezz'ora dall'attivazione del workflow su GitHub."
        : "Nessun annuncio con questi filtri.";
    }
  }

  var CHIAVE_VISTA = "cacciatore.vista", CHIAVE_TEMA = "cacciatore.tema";
  function salvaTesto(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* storage non disponibile */ } }
  function leggiTesto(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }

  function impostaVista(v) {
    el.elenco.classList.toggle("griglia", v === "griglia");
    el["v-griglia"].setAttribute("aria-pressed", v === "griglia");
    el["v-elenco"].setAttribute("aria-pressed", v !== "griglia");
    salvaTesto(CHIAVE_VISTA, v);
  }
  function temaCorrente() {
    var t = document.documentElement.getAttribute("data-theme");
    if (t) return t;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  function alternaTema() {
    var nuovo = temaCorrente() === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", nuovo);
    salvaTesto(CHIAVE_TEMA, nuovo);
    var m = document.querySelector('meta[name="theme-color"]');
    if (m) m.setAttribute("content", nuovo === "dark" ? "#121315" : "#f2f3f4");
  }

  function avvia() {
    impostaVista(leggiTesto(CHIAVE_VISTA) === "griglia" ? "griglia" : "elenco");
    el["v-elenco"].addEventListener("click", function () { impostaVista("elenco"); });
    el["v-griglia"].addEventListener("click", function () { impostaVista("griglia"); });
    el.tema.addEventListener("click", alternaTema);
    impostaModalita(leggiTesto(CHIAVE_MOD) === "vintage" ? "vintage" : "moderno", false);
    el["m-vintage"].addEventListener("click", function () { impostaModalita("vintage", true); ridisegna(); });
    el["m-moderno"].addEventListener("click", function () { impostaModalita("moderno", true); ridisegna(); });
    el.pannello.open = el.fonti.open = window.matchMedia("(min-width: 860px)").matches;
    ["f-testo", "f-tipo", "f-marca", "f-paese", "f-fonte", "f-rarita", "f-max", "f-ordine", "f-affari", "f-nofuoriue", "f-solopreferiti", "f-nascosti"]
      .forEach(function (id) { el[id].addEventListener("input", ridisegna); });

    fetch("data/items.json", { cache: "no-cache" })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) {
        dati = d;
        el.stato.textContent = d.aggiornato ? "Ultima novità registrata " + fa(d.aggiornato) : "";
        conteggiModalita();
        popolaPaesi();
        popolaFonti();
        popolaMarche();
        disegna();
      })
      .catch(function () {
        el.stato.textContent = "";
        el.vuoto.hidden = false;
        el.vuoto.textContent = "Nessun dato ancora. Se hai appena attivato il progetto, aspetta la prima esecuzione del workflow.";
      });
  }
  avvia();
})();
