/**
 * TASK - DB circoli condiviso (Google Apps Script, pubblicato come "App web").
 *
 * Il foglio resta PRIVATO: lo legge solo questo script, che gira con
 * l'account del proprietario. Un client vede solo le risposte alle sue domande (i circoli che
 * cerca, l'elenco province -> regione), mai l'elenco completo dei circoli.
 * In questo file non ci sono token, URL o dati: puo' stare nel repo pubblico.
 *
 * Fogli (riga 1 = intestazioni):
 *   Circoli : Circolo | Provincia | Regione | Aggiunto il | Da
 *   Utenti  : Nome | Token | Attivo        (Attivo = casella di controllo: togli la spunta per bloccare)
 *             + contatori aggiunti da soli al primo uso:
 *             Tennis | Beach | Campionato | Coeff. beach | Caricamento circoli | Ultimo uso | Versione
 * Proprieta' dello script (Impostazioni progetto > Proprieta' script):
 *   VERSIONE_MINIMA   es. 2.1.0 -> le versioni di TASK piu' vecchie vengono rifiutate
 *
 * Richiesta: POST con corpo JSON {token, versione, azione, ...}. Il token NON va nell'URL.
 *   province  -> {province: {provincia: regione}}
 *   cerca     {nomi: [...]}                 -> {trovati: {NOME MAIUSCOLO: [provincia, regione]}}
 *   stato     -> {totale, ultima_aggiunta}
 *   aggiungi  {righe: [[circolo, provincia], ...]} -> {aggiunti, gia_presenti, totale}
 *   uso       {funzione: tennis|beach|campionato|coeff_beach|circoli} -> {}  (+1 nel contatore dell'utente)
 * Risposta sempre JSON {ok: true, ...} oppure {ok: false, errore: "Err NN: ..."}
 * (le App web non possono restituire codici HTTP d'errore).
 */

const FOGLIO_CIRCOLI = 'Circoli';
const FOGLIO_UTENTI = 'Utenti';
const MAX_NOMI = 2000;       // circoli cercati in una richiesta (un torneo ne ha molti meno)
const MAX_RIGHE = 500;       // circoli aggiunti in una richiesta
const ATTESA_LOCK_MS = 20000;

function doPost(e) {
  let risposta;
  try {
    let richiesta;
    try {
      richiesta = JSON.parse(e.postData.contents);
    } catch (err) {
      throw new Error('Err 63: richiesta non leggibile (non e\' JSON).');
    }
    const utente = autentica_(richiesta);
    switch (richiesta.azione) {
      case 'province': risposta = { province: province_(leggiCircoli_()) }; break;
      case 'cerca':    risposta = cerca_(richiesta.nomi); break;
      case 'stato':    risposta = stato_(); break;
      case 'aggiungi': risposta = aggiungi_(richiesta.righe, utente.nome, richiesta.versione); break;
      case 'uso':      risposta = registraUso_(richiesta.funzione, utente, richiesta.versione); break;
      default: throw new Error('Err 63: azione sconosciuta: ' + richiesta.azione);
    }
    risposta.ok = true;
  } catch (err) {
    risposta = { ok: false, errore: String(err && err.message ? err.message : err) };
  }
  return ContentService.createTextOutput(JSON.stringify(risposta))
    .setMimeType(ContentService.MimeType.JSON);
}

function doGet() {
  return ContentService.createTextOutput('TASK DB circoli: usare POST.');
}

// ---------------------------------------------------------------------------
// Accesso: un token per utente (foglio Utenti) + versione minima dell'app
// ---------------------------------------------------------------------------
function autentica_(r) {
  if (!r || typeof r.token !== 'string' || r.token.trim() === '') {
    throw new Error('Err 61: codice di accesso mancante.');
  }
  const minima = PropertiesService.getScriptProperties().getProperty('VERSIONE_MINIMA');
  if (minima && confrontaVersioni_(String(r.versione || '0'), minima) < 0) {
    throw new Error('Err 62: TASK ' + r.versione + ' non e\' piu\' ammessa, serve almeno la ' + minima + '.');
  }
  const utenti = foglio_(FOGLIO_UTENTI).getDataRange().getValues().slice(1);
  const token = r.token.trim();
  const i = utenti.findIndex(function (x) { return String(x[1]).trim() === token; });
  if (i < 0 || utenti[i][2] !== true) {
    throw new Error('Err 61: codice di accesso non valido o disattivato.');
  }
  // anche la riga del foglio (serve al contatore); riga 1 = intestazioni
  return { nome: String(utenti[i][0]).trim(), riga: i + 2 };
}

function confrontaVersioni_(a, b) {
  const pa = a.split('.').map(Number), pb = b.split('.').map(Number);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const d = (pa[i] || 0) - (pb[i] || 0);
    if (d !== 0) return d;
  }
  return 0;
}

// ---------------------------------------------------------------------------
// Lettura
// ---------------------------------------------------------------------------
function foglio_(nome) {
  const f = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(nome);
  if (!f) throw new Error('Err 63: nel foglio Google manca la scheda «' + nome + '».');
  return f;
}

// Testi cosi' come si vedono nel foglio (niente conversioni in numeri o date).
function leggiCircoli_() {
  return foglio_(FOGLIO_CIRCOLI).getDataRange().getDisplayValues().slice(1)
    .filter(function (r) { return String(r[0]).trim() !== ''; });
}

// Stessa chiave di players.mappa_clubs: nome del circolo, spazi ai lati tolti, maiuscolo.
function chiave_(nome) {
  return String(nome).trim().toUpperCase();
}

// Stesso confronto di data_update._chiave_provincia: 'Bolzano/Bozen' -> 'bolzano', accenti tolti.
function chiaveProvincia_(testo) {
  return String(testo).split('/')[0].normalize('NFKD').replace(/[̀-ͯ]/g, '')
    .toLowerCase().split(/\s+/).filter(Boolean).join(' ');
}

function province_(righe) {
  const out = {};
  righe.forEach(function (r) {
    const p = String(r[1]).trim();
    if (p) out[p] = String(r[2]).trim();
  });
  return out;
}

function cerca_(nomi) {
  if (!Array.isArray(nomi)) throw new Error('Err 63: «nomi» deve essere un elenco.');
  if (nomi.length > MAX_NOMI) throw new Error('Err 63: troppi circoli in una richiesta (' + nomi.length + ').');
  const indice = {};
  leggiCircoli_().forEach(function (r) {
    indice[chiave_(r[0])] = [String(r[1]).trim(), String(r[2]).trim()];
  });
  const trovati = {};
  nomi.forEach(function (n) {
    const k = chiave_(n);
    if (indice[k]) trovati[k] = indice[k];
  });
  return { trovati: trovati };
}

function stato_() {
  const righe = leggiCircoli_();
  const ultima = righe.length ? String(righe[righe.length - 1][3]).trim() : '';
  return { totale: righe.length, ultima_aggiunta: ultima };
}

// ---------------------------------------------------------------------------
// Scrittura: solo aggiunte in fondo, tutti i controlli PRIMA di scrivere
// ---------------------------------------------------------------------------
function aggiungi_(righe, utente, versione) {
  if (!Array.isArray(righe) || righe.length === 0) {
    throw new Error('Err 51: nessun circolo con provincia da aggiungere.');
  }
  if (righe.length > MAX_RIGHE) throw new Error('Err 63: troppi circoli in una richiesta (' + righe.length + ').');

  const lock = LockService.getScriptLock();
  if (!lock.tryLock(ATTESA_LOCK_MS)) {
    throw new Error('Err 64: il DB circoli e\' occupato da un altro utente, riprova tra qualche secondo.');
  }
  try {
    const foglio = foglio_(FOGLIO_CIRCOLI);
    const esistenti = leggiCircoli_();                       // riletti DENTRO il lock
    const province = province_(esistenti);
    const perChiave = {};
    Object.keys(province).forEach(function (p) { perChiave[chiaveProvincia_(p)] = p; });

    // 1. controlli: se anche una sola provincia non e' nota non si aggiunge niente (come oggi)
    const sconosciute = [];
    righe.forEach(function (r) {
      if (!Array.isArray(r) || r.length < 2 || String(r[0]).trim() === '') {
        throw new Error('Err 63: riga non valida: ' + JSON.stringify(r));
      }
      if (!perChiave[chiaveProvincia_(r[1])]) sconosciute.push('«' + String(r[0]).trim() + '»: «' + r[1] + '»');
    });
    if (sconosciute.length) {
      throw new Error('Err 49: province non riconosciute, nessun circolo aggiunto: ' + sconosciute.slice(0, 5).join('; ')
        + (sconosciute.length > 5 ? ' e altre ' + (sconosciute.length - 5) : ''));
    }

    // 2. duplicati (gia' nel foglio o ripetuti nella richiesta)
    const chiavi = {};
    esistenti.forEach(function (r) { chiavi[chiave_(r[0])] = true; });
    const quando = Utilities.formatDate(new Date(), 'Europe/Rome', 'yyyy-MM-dd HH:mm:ss');
    const da = utente + ' (TASK ' + (versione || '?') + ')';
    const nuovi = [], giaPresenti = [];
    righe.forEach(function (r) {
      const circolo = String(r[0]).trim();
      const k = chiave_(circolo);
      if (chiavi[k]) { giaPresenti.push(circolo); return; }
      chiavi[k] = true;
      const provincia = perChiave[chiaveProvincia_(r[1])];
      nuovi.push([circolo, provincia, province[provincia], quando, da]);
    });

    // 3. append in un colpo solo, come testo (niente conversioni di Sheets)
    if (nuovi.length) {
      const zona = foglio.getRange(foglio.getLastRow() + 1, 1, nuovi.length, 5);
      zona.setNumberFormat('@');
      zona.setValues(nuovi);
      SpreadsheetApp.flush();
    }
    return {
      aggiunti: nuovi.map(function (n) { return n.slice(0, 3); }),
      gia_presenti: giaPresenti,
      totale: esistenti.length + nuovi.length
    };
  } finally {
    lock.releaseLock();
  }
}


// ---------------------------------------------------------------------------
// contatore delle funzioni usate (foglio Utenti), una colonna per funzione.
// Si conta quando un'elaborazione PARTE (non i clic). Le colonne mancanti si aggiungono da sole,
// in fondo alla riga di intestazione e sempre nello stesso ordine.
// ---------------------------------------------------------------------------
const COLONNE_USO = {
  tennis: 'Tennis', beach: 'Beach', campionato: 'Campionato',
  coeff_beach: 'Coeff. beach', circoli: 'Caricamento circoli'
};
const COLONNA_ULTIMO_USO = 'Ultimo uso';
const COLONNA_VERSIONE = 'Versione';

function registraUso_(funzione, utente, versione) {
  const titolo = COLONNE_USO[funzione];
  if (!titolo) throw new Error('Err 63: funzione sconosciuta per il contatore: ' + funzione);
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(ATTESA_LOCK_MS)) {
    throw new Error('Err 64: il DB e\' occupato da un altro utente, riprova tra qualche secondo.');
  }
  try {
    const foglio = foglio_(FOGLIO_UTENTI);
    const titoli = Object.keys(COLONNE_USO).map(function (k) { return COLONNE_USO[k]; })
      .concat([COLONNA_ULTIMO_USO, COLONNA_VERSIONE]);
    const col = colonne_(foglio, titoli);
    const cella = foglio.getRange(utente.riga, col[titolo]);
    cella.setValue((Number(cella.getValue()) || 0) + 1);
    foglio.getRange(utente.riga, col[COLONNA_ULTIMO_USO]).setNumberFormat('@')
      .setValue(Utilities.formatDate(new Date(), 'Europe/Rome', 'yyyy-MM-dd HH:mm'));
    foglio.getRange(utente.riga, col[COLONNA_VERSIONE]).setNumberFormat('@').setValue(String(versione || '?'));
    SpreadsheetApp.flush();
  } finally {
    lock.releaseLock();
  }
  return {};
}

// {titolo: numero di colonna}; le intestazioni che mancano vengono scritte in fondo alla riga 1.
function colonne_(foglio, titoli) {
  const ultima = Math.max(foglio.getLastColumn(), 1);
  const intestazioni = foglio.getRange(1, 1, 1, ultima).getDisplayValues()[0]
    .map(function (x) { return String(x).trim(); });
  const out = {};
  let prossima = ultima + 1;
  titoli.forEach(function (t) {
    const i = intestazioni.indexOf(t);
    if (i >= 0) {
      out[t] = i + 1;
    } else {
      foglio.getRange(1, prossima).setValue(t);
      out[t] = prossima++;
    }
  });
  return out;
}
