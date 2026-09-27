/* ==========================================================================
   T.A.S.K — comportamento delle pagine
   Un unico file per tutte le pagine: ogni blocco si attiva solo se trova nella
   pagina gli elementi che gli servono (riconosciuti dagli attributi data-*).
   Scopo: l'utente non deve poter inviare un form incompleto o incoerente, così
   gli errori di input non arrivano nemmeno a Flask. ATTENZIONE: è solo la prima
   barriera. Chi vuole può aggirare il browser, quindi Flask deve ricontrollare.
   ========================================================================== */
(function () {
  "use strict";

  // Funzioni da rieseguire quando si torna alla pagina col tasto "Indietro"
  // (il browser ripristina la pagina com'era, overlay di attesa compreso).
  const risincronizza = [];

  /* ---- 1. Zona di caricamento file ----------------------------------------
     - mostra il nome del file scelto;
     - rifiuta subito estensioni sbagliate (accept="..." dell'input);
     - data-controllo-nome="REGEX": se il nome del file non la contiene mostra
       l'avviso .dropzone-avviso (non blocca, avverte). */
  document.querySelectorAll(".dropzone").forEach(function (zona) {
    const input = zona.querySelector('input[type="file"]');
    const nome = zona.querySelector(".dropzone-nome");
    const avviso = zona.parentElement.querySelector(".dropzone-avviso");
    const testoVuoto = nome.textContent;
    const ammessi = (input.getAttribute("accept") || "")
      .split(",").map(function (s) { return s.trim().toLowerCase(); }).filter(Boolean);
    const controllo = input.dataset.controlloNome ? new RegExp(input.dataset.controlloNome, "i") : null;

    function sync() {
      // anche con `multiple`: controlla tutti i file e il numero massimo (data-max-file)
      const files = Array.prototype.slice.call(input.files || []);
      zona.classList.remove("ok", "errore");
      if (avviso) avviso.hidden = true;
      if (!files.length) { nome.textContent = testoVuoto; return; }

      const massimo = parseInt(input.dataset.maxFile || (input.multiple ? "99" : "1"), 10);
      if (files.length > massimo) {
        input.value = "";
        zona.classList.add("errore");
        nome.textContent = files.length + " file: al massimo " + massimo;
        return;
      }
      const sbagliato = files.find(function (f) {
        return ammessi.length && ammessi.indexOf("." + f.name.split(".").pop().toLowerCase()) === -1;
      });
      if (sbagliato) {
        input.value = "";                       // scarto i file sbagliati
        zona.classList.add("errore");
        nome.textContent = "«" + sbagliato.name + "» non va bene: serve un file " + ammessi.join(" o ");
        return;
      }
      zona.classList.add("ok");
      nome.textContent = files.map(function (f) { return f.name; }).join(" + ");
      if (avviso && controllo && files.some(function (f) { return !controllo.test(f.name); })) avviso.hidden = false;
    }

    input.addEventListener("change", sync);
    ["dragenter", "dragover"].forEach(function (ev) {
      input.addEventListener(ev, function () { zona.classList.add("sopra"); });
    });
    ["dragleave", "drop"].forEach(function (ev) {
      input.addEventListener(ev, function () { zona.classList.remove("sopra"); });
    });
    risincronizza.push(sync);
  });

  /* ---- 2. Date collegate ----------------------------------------------------
     data-non-prima-di="id": la data fine non può essere prima della data inizio.
     Il calendario blocca i giorni precedenti; se l'utente sposta in avanti la data
     inizio oltre la data fine, la data fine viene svuotata (va riscelta). */
  document.querySelectorAll("input[data-non-prima-di]").forEach(function (fine) {
    const inizio = document.getElementById(fine.dataset.nonPrimaDi);
    if (!inizio) return;
    function sync() {
      fine.min = inizio.value || "";
      if (inizio.value && fine.value && fine.value < inizio.value) fine.value = "";
    }
    inizio.addEventListener("input", sync);
    inizio.addEventListener("change", sync);
    risincronizza.push(sync);
  });

  /* ---- 3. Sezioni che compaiono solo con una certa scelta ------------------
     data-se="nome_radio=valore": la sezione è visibile solo se quel radio è scelto.
     Quando è nascosta i suoi campi vengono DISATTIVATI: il browser non li
     controlla e non li invia (in Flask request.form.get(...) restituisce None). */
  document.querySelectorAll("[data-se]").forEach(function (box) {
    const parti = box.dataset.se.split("=");
    const nomeRadio = parti[0], valore = parti[1];
    const form = box.closest("form");
    function sync() {
      const scelto = form.querySelector('input[name="' + nomeRadio + '"]:checked');
      const attivo = !!scelto && scelto.value === valore;
      box.hidden = !attivo;
      box.querySelectorAll("input, select, textarea").forEach(function (el) { el.disabled = !attivo; });
    }
    form.querySelectorAll('input[name="' + nomeRadio + '"]').forEach(function (r) {
      r.addEventListener("change", sync);
    });
    risincronizza.push(sync);
  });

  /* ---- 4. Due tendine che non possono avere lo stesso valore ---------------
     data-diversa-da="id": nella tendina Ospite la squadra scelta come Casa è
     grigia e non selezionabile (e viceversa). */
  const tendine = Array.prototype.slice.call(document.querySelectorAll("select[data-diversa-da]"));
  function syncTendine() {
    tendine.forEach(function (sel) {
      const altra = document.getElementById(sel.dataset.diversaDa);
      if (!altra) return;
      Array.prototype.forEach.call(sel.options, function (o) {
        if (o.value) o.disabled = (o.value === altra.value);
      });
      if (sel.value && sel.value === altra.value) sel.selectedIndex = 0;
    });
  }
  if (tendine.length) {
    tendine.forEach(function (sel) { sel.addEventListener("change", syncTendine); });
    risincronizza.push(syncTendine);
  }

  /* ---- 5. Filtro del registro nella pagina di download --------------------- */
  document.querySelectorAll("input[data-filtro-log]").forEach(function (radio) {
    const lista = document.getElementById(radio.dataset.filtroLog);
    if (!lista) return;
    function sync() {
      if (radio.checked) lista.classList.toggle("solo-problemi", radio.value === "problemi");
    }
    radio.addEventListener("change", sync);
    risincronizza.push(sync);
  });

  /* ---- 6. Schermata di attesa ------------------------------------------------ */
  function mmss(secondi) {
    const s = Math.max(0, Math.floor(secondi));
    return String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
  }

  const overlay = document.getElementById("overlay");
  let orologio = null;
  function mostraAttesa(testo) {
    if (!overlay) return;
    if (testo) overlay.querySelector(".overlay-testo").textContent = testo;
    const t0 = Date.now();
    const out = overlay.querySelector(".overlay-tempo");
    function tick() {
      out.textContent = "Tempo trascorso " + mmss((Date.now() - t0) / 1000);
    }
    tick();
    orologio = setInterval(tick, 1000);
    overlay.hidden = false;
  }
  risincronizza.push(function () {
    if (overlay) overlay.hidden = true;
    clearInterval(orologio);
  });

  /* ---- 7. Form guidati --------------------------------------------------------
     Il pulsante di invio resta disattivato finché manca qualcosa, e sotto compare
     l'elenco di cosa manca (preso da data-etichetta del contenitore del campo).
     All'invio: pulsante bloccato (niente doppio click = niente doppia elaborazione)
     e schermata di attesa con il testo di data-attesa. */
  function aggiornaForm(form) {
    const pulsante = form.querySelector('button[type="submit"]');
    const box = form.querySelector(".mancanti");
    const mancanti = [];
    Array.prototype.forEach.call(form.elements, function (el) {
      if (!el.willValidate || el.checkValidity()) return;
      const contenitore = el.closest("[data-etichetta]");
      const nome = contenitore ? contenitore.dataset.etichetta : (el.name || "un campo");
      if (mancanti.indexOf(nome) === -1) mancanti.push(nome);
    });
    if (pulsante) pulsante.disabled = mancanti.length > 0;
    if (box) {
      box.textContent = mancanti.length ? "Da completare: " + mancanti.join(", ") : "Tutto pronto.";
      box.classList.toggle("pronto", mancanti.length === 0);
    }
  }

  document.querySelectorAll("form.form-guidato").forEach(function (form) {
    form.addEventListener("input", function () { aggiornaForm(form); });
    form.addEventListener("change", function () { aggiornaForm(form); });
    form.addEventListener("submit", function (e) {
      if (!form.checkValidity()) { e.preventDefault(); form.reportValidity(); return; }
      if (form.dataset.inviato) { e.preventDefault(); return; }
      form.dataset.inviato = "1";
      const pulsante = form.querySelector('button[type="submit"]');
      if (pulsante) pulsante.disabled = true;
      mostraAttesa(form.dataset.attesa);
    });
    risincronizza.push(function () {
      delete form.dataset.inviato;
      aggiornaForm(form);
    });
  });

  /* ---- 8. Elaborazione in diretta (Server-Sent Events) ----------------------
     Si attiva solo in elaborazione.html ([data-stream]). Il server manda eventi JSON con un campo "tipo":
       log          {messaggio, livello}          -> nuova riga nel registro
       avanzamento  {fase, fatti, totale, percentuale, trascorso, stima_residua}
       fine         {}                            -> vai alla pagina di download
       errore       {messaggio, dettaglio}        -> mostra il crash, niente redirect
     Se la connessione cade EventSource riprova da solo (non la chiudiamo noi) e manda
     l'ultimo id ricevuto: il server riprende da lì, senza righe doppie. */
  const diretta = document.querySelector("[data-stream]");
  if (diretta) avviaDiretta(diretta);

  function avviaDiretta(p) {
    const titolo = document.getElementById("diretta-titolo");
    const intro = document.getElementById("diretta-intro");
    const fase = p.querySelector(".diretta-fase");
    const conta = p.querySelector(".diretta-conta");
    const barra = p.querySelector(".barra");
    const riempimento = p.querySelector(".barra-riempimento");
    const tempo = p.querySelector(".diretta-tempo");
    const stima = p.querySelector(".diretta-stima");
    const connessione = p.querySelector(".diretta-connessione");
    const fine = p.querySelector(".diretta-fine");
    const registro = document.getElementById("registro-diretta");
    const chipErr = document.getElementById("conta-err");
    const chipAtt = document.getElementById("conta-att");
    const pannelloErrore = document.getElementById("diretta-errore");

    let nErr = 0, nAtt = 0, concluso = false;
    let t0 = Date.now();                       // riallineato dal server con "trascorso"
    function aggiornaTempo() {
      tempo.textContent = "Tempo trascorso " + mmss((Date.now() - t0) / 1000);
    }
    const orologioDiretta = setInterval(aggiornaTempo, 1000);

    function avviso(testo, grave) {
      connessione.textContent = testo;
      connessione.classList.toggle("grave", !!grave);
      connessione.hidden = !testo;
    }

    function aggiungiRiga(testo, livello) {
      // resto "incollato" in fondo solo se l'utente non è risalito a leggere
      const inFondo = registro.scrollHeight - registro.scrollTop - registro.clientHeight < 40;
      const li = document.createElement("li");
      li.className = livello || "info";
      li.textContent = testo;
      registro.appendChild(li);
      if (livello === "err") { nErr++; chipErr.textContent = nErr + (nErr === 1 ? " errore" : " errori"); chipErr.hidden = false; }
      if (livello === "att") { nAtt++; chipAtt.textContent = nAtt + " da controllare"; chipAtt.hidden = false; }
      if (inFondo) registro.scrollTop = registro.scrollHeight;
    }

    function aggiornaAvanzamento(d) {
      if (typeof d.trascorso === "number") { t0 = Date.now() - d.trascorso * 1000; aggiornaTempo(); }
      if (d.fase) fase.textContent = d.fase;
      if (d.totale > 0) {
        conta.textContent = d.fatti + " / " + d.totale;
        barra.classList.remove("indeterminata");
        riempimento.style.width = d.percentuale + "%";
        barra.setAttribute("aria-valuenow", d.percentuale);
      }
      if (typeof d.stima_residua === "number") {
        // nel campionato la stima vale per la squadra in corso (casa, poi ospite)
        const coda = /^(Casa|Ospite)/.test(d.fase || "") ? " per questa squadra" : "";
        stima.textContent = d.stima_residua < 60
          ? "Meno di un minuto" + coda
          : "Circa " + Math.round(d.stima_residua / 60) + " min rimanenti" + coda;
      } else {
        stima.textContent = "";
      }
    }

    function chiudi() {
      concluso = true;
      sorgente.close();                          // niente riconnessioni dopo la fine
      clearInterval(orologioDiretta);
      avviso("");
    }

    const sorgente = new EventSource(p.dataset.stream);
    sorgente.onopen = function () { avviso(""); };
    sorgente.onmessage = function (evento) {
      const d = JSON.parse(evento.data);
      if (d.tipo === "log") {
        aggiungiRiga(d.messaggio, d.livello);
      } else if (d.tipo === "avanzamento") {
        aggiornaAvanzamento(d);
      } else if (d.tipo === "fine") {
        chiudi();
        titolo.textContent = p.dataset.titoloFine || "Completato";   // testo diverso per gli aggiornamenti
        intro.hidden = true;
        fase.textContent = "Completato";
        barra.classList.remove("indeterminata");
        barra.classList.add("completata");
        riempimento.style.width = "100%";
        stima.textContent = "";
        fine.hidden = false;
        setTimeout(function () { window.location.href = p.dataset.fine; }, 1500);
      } else if (d.tipo === "errore") {
        chiudi();
        titolo.textContent = "Elaborazione interrotta";
        intro.textContent = "Il registro qui sotto mostra fin dove è arrivato il controllo prima di fermarsi.";
        fase.textContent = "Interrotta";
        barra.classList.remove("indeterminata");
        barra.classList.add("fallita");
        stima.textContent = "";
        pannelloErrore.querySelector(".diretta-errore-messaggio").textContent = d.messaggio;
        pannelloErrore.querySelector(".diretta-errore-dettaglio").textContent = d.dettaglio || "";
        // "cosa fare" da codici_errori.csv; il traceback solo per gli errori del programma
        const rimedio = pannelloErrore.querySelector(".diretta-errore-rimedio");
        rimedio.textContent = d.rimedio ? "Cosa fare: " + d.rimedio : "";
        rimedio.hidden = !d.rimedio;
        pannelloErrore.querySelector(".dettaglio-errore").hidden = !d.dettaglio;
        pannelloErrore.hidden = false;
        pannelloErrore.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    };
    sorgente.onerror = function () {
      if (concluso) return;
      if (sorgente.readyState === EventSource.CLOSED) {
        // il server ha risposto con un errore (es. 404): non riproverà più
        clearInterval(orologioDiretta);
        avviso("Il server non trova più questa elaborazione: il programma è stato chiuso o riavviato? " +
               "Il controllo è stato interrotto, ricomincia dal modulo.", true);
      } else {
        avviso("Connessione persa con il programma, riprovo… (l'elaborazione continua)");
      }
    };
  }

  // Avvio + ritorno con "Indietro"
  risincronizza.forEach(function (f) { f(); });
  window.addEventListener("pageshow", function (e) {
    if (e.persisted) risincronizza.forEach(function (f) { f(); });
  });
})();
