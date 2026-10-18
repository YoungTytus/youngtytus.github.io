// Wczytanie i walidacja paczki eksportu (docs/SPEC_STRONA.md, sekcja 5).
//
// Dwa tryby:
//   paczka   – EKSPORT=<katalog> z manifest.json, korzysci.json, akty.json, slowniki.json, akty/
//   przyklad – brak EKSPORT: plik docs/strona/przyklad_eksportu.json (bez plików PDF)
//
// Każdy błąd przerywa budowanie z komunikatem: który plik, który rekord, które pole.
// Strona niczego tu nie liczy ani nie uzupełnia; sprawdza tylko zgodność z kontraktem.

import { createHash } from 'node:crypto';
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import Ajv2020 from 'ajv/dist/2020.js';
import addFormats from 'ajv-formats';

const KATALOG_STRONY = process.env.STRONA_KATALOG ?? process.cwd();
const SCIEZKA_SCHEMATU = path.join(KATALOG_STRONY, 'schema', 'eksport.schema.json');
const SCIEZKA_PRZYKLADU = path.resolve(KATALOG_STRONY, 'data', 'przyklad_eksportu.json');
const SCIEZKA_EKSPORTU = path.resolve(KATALOG_STRONY, 'data', 'eksport');
const PLIKI_DANYCH = ['korzysci.json', 'akty.json', 'slowniki.json'];

export class BladEksportu extends Error {
  constructor(bledy) {
    super(`Eksport nie przeszedł walidacji (${bledy.length}):\n  - ${bledy.join('\n  - ')}`);
    this.bledy = bledy;
  }
}

export const sha256 = (bajty) => createHash('sha256').update(bajty).digest('hex');

let walidatory = null;
function pobierzWalidatory() {
  if (walidatory) return walidatory;
  const ajv = new Ajv2020({ allErrors: true, strict: false });
  addFormats(ajv);
  ajv.addSchema(JSON.parse(readFileSync(SCIEZKA_SCHEMATU, 'utf8')), 'eksport');
  const ref = (nazwa) => ajv.getSchema(`eksport#/$defs/${nazwa}`);
  walidatory = { Korzysc: ref('Korzysc'), Akt: ref('Akt'), Slowniki: ref('Slowniki'), Manifest: ref('Manifest') };
  return walidatory;
}

function opiszBledy(walidator, gdzie) {
  return (walidator.errors ?? []).map((e) => {
    const pole = e.instancePath || '(rekord)';
    const extra = e.params?.additionalProperty ? ` „${e.params.additionalProperty}”` : '';
    const dozwolone = e.params?.allowedValues ? ` (dozwolone: ${e.params.allowedValues.join(', ')})` : '';
    return `${gdzie}${pole}: ${e.message}${extra}${dozwolone}`;
  });
}

function waliduj(nazwa, dane, gdzie, bledy) {
  const w = pobierzWalidatory()[nazwa];
  if (!w(dane)) bledy.push(...opiszBledy(w, gdzie));
}

const czyData = (v) => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v);

// Kontrole, których nie wyrazi JSON Schema: unikalność, odwołania, kolejność osi czasu.
function sprawdzSpojnosc({ korzysci, akty, slowniki }, bledy, ostrzezenia) {
  const ids = new Set();
  const slugi = new Set();
  korzysci.forEach((k, i) => {
    const gdzie = `korzysci[${i}] (${k.id})`;
    if (ids.has(k.id)) bledy.push(`${gdzie}: powtórzony id`);
    if (slugi.has(k.slug)) bledy.push(`${gdzie}: powtórzony slug „${k.slug}”`);
    ids.add(k.id);
    slugi.add(k.slug);

    for (const [pole, slownik] of [['rodzaj_korzysci', 'rodzaj_korzysci'], ['status', 'status']]) {
      if (!(k[pole] in slowniki[slownik])) bledy.push(`${gdzie}/${pole}: brak etykiety „${k[pole]}” w slowniki.${slownik}`);
    }
    k.sytuacje.forEach((s) => {
      if (!(s in slowniki.sytuacje)) bledy.push(`${gdzie}/sytuacje: kod „${s}” nie istnieje w slowniki.sytuacje`);
    });

    const akt = k.ile.aktualna;
    if (akt && akt.wartosc == null && !(akt.warianty?.length)) {
      bledy.push(`${gdzie}/ile/aktualna: brak wartości i wariantów (użyj null, gdy nie ustalono)`);
    }
    if (k.ile.rozwiazanie === 'regula_procentowa' && !k.ile.regula) {
      bledy.push(`${gdzie}/ile/regula: wymagana dla rozwiązania regula_procentowa`);
    }

    // Oś czasu posortowana rosnąco po "od"; wpis bez daty początku może stać tylko na początku.
    let poprzednie = null;
    k.ile.os_czasu.forEach((w, j) => {
      if (w.wartosc == null && !(w.warianty?.length)) bledy.push(`${gdzie}/ile/os_czasu/${j}: brak wartości i wariantów`);
      if (!czyData(w.od)) {
        if (poprzednie) bledy.push(`${gdzie}/ile/os_czasu/${j}: wpis bez daty „od” po wpisie z datą (oś musi być posortowana)`);
        return;
      }
      if (poprzednie && w.od < poprzednie) bledy.push(`${gdzie}/ile/os_czasu/${j}: „od” ${w.od} wcześniejsze niż poprzedni wpis ${poprzednie}`);
      poprzednie = w.od;
    });

    // Termin bez rodzaju: pomijamy i zgłaszamy (SPEC 5.4), nie przerywamy budowania.
    k.do_kiedy = k.do_kiedy.filter((t, j) => {
      if (t.rodzaj) return true;
      ostrzezenia.push(`${gdzie}/do_kiedy/${j}: termin bez pola „rodzaj” pominięty`);
      return false;
    });
  });

  const elis = new Set();
  akty.forEach((a, i) => {
    const gdzie = `akty[${i}] (${a.eli})`;
    if (elis.has(a.eli)) bledy.push(`${gdzie}: powtórzone eli`);
    elis.add(a.eli);
    a.korzysci.forEach((id) => {
      if (!ids.has(id)) ostrzezenia.push(`${gdzie}/korzysci: „${id}” nie ma rekordu w korzysci.json`);
    });
    const sciezki = new Set();
    a.pliki.forEach((p, j) => {
      if (p.plik.split('/').includes('..')) bledy.push(`${gdzie}/pliki/${j}/plik: ścieżka nie może zawierać „..”`);
      if (sciezki.has(p.plik)) bledy.push(`${gdzie}/pliki/${j}/plik: powtórzona ścieżka`);
      sciezki.add(p.plik);
      if (p.rodzaj === 'U' && !p.data_stanu) bledy.push(`${gdzie}/pliki/${j}: plik U wymaga data_stanu`);
      if (p.rodzaj === 'TJ' && !p.eli_obwieszczenia) bledy.push(`${gdzie}/pliki/${j}: plik TJ wymaga eli_obwieszczenia`);
    });
  });
}

// SHA256SUMS w formacie sha256sum: "<sha256>  <ścieżka>". Ścieżka względem paczki albo katalogu akty/.
export function parsujSha256Sums(tekst) {
  const mapa = new Map();
  tekst.split(/\r?\n/).forEach((linia) => {
    const m = linia.match(/^([0-9a-f]{64}) [ *](.+)$/);
    if (!m) return;
    mapa.set(m[2].replace(/^\.\//, '').replace(/^akty\//, ''), m[1]);
  });
  return mapa;
}

function sprawdzPliki(katalog, manifest, akty, sprawdzSumy, bledy, tylkoOdsylacze = false) {
  // 1. pliki danych zgodne z manifestem
  if (!manifest.pliki) {
    bledy.push('manifest.json/pliki: brak sum SHA-256 plików paczki');
    return new Set();
  }
  for (const nazwa of [...PLIKI_DANYCH, 'akty/SHA256SUMS']) {
    const sciezka = path.join(katalog, nazwa);
    if (!existsSync(sciezka)) { bledy.push(`${nazwa}: brak pliku w paczce`); continue; }
    const oczekiwana = manifest.pliki[nazwa];
    if (!oczekiwana) { bledy.push(`manifest.json/pliki: brak sumy dla ${nazwa}`); continue; }
    const faktyczna = sha256(readFileSync(sciezka));
    if (faktyczna !== oczekiwana) bledy.push(`${nazwa}: SHA-256 ${faktyczna} różni się od manifestu (${oczekiwana})`);
  }

  // 2. każdy plik aktu istnieje, a suma z pliku = SHA256SUMS = akty.json
  const sumy = existsSync(path.join(katalog, 'akty/SHA256SUMS'))
    ? parsujSha256Sums(readFileSync(path.join(katalog, 'akty/SHA256SUMS'), 'utf8'))
    : new Map();
  const dostepne = new Set();
  akty.forEach((a) => a.pliki.forEach((p) => {
    const gdzie = `akty.json ${a.eli} → ${p.plik}`;
    const sciezka = path.join(katalog, p.plik);
    if (tylkoOdsylacze) {
      const zSums = sumy.get(p.plik.replace(/^akty\//, ''));
      if (zSums !== p.sha256) bledy.push(`${gdzie}: SHA256SUMS nie zgadza się z akty.json`);
      if (p.url_zrodla != null && !/^https:\/\/api\.sejm\.gov\.pl\/eli\/acts\//.test(p.url_zrodla)) bledy.push(`${gdzie}: niepoprawny adres PDF w API Sejmu`);
      return;
    }
    if (!existsSync(sciezka)) { bledy.push(`${gdzie}: plik nie istnieje w paczce`); return; }
    dostepne.add(p.plik);
    if (!sprawdzSumy) return;
    const bajty = readFileSync(sciezka);
    const faktyczna = sha256(bajty);
    const zSums = sumy.get(p.plik.replace(/^akty\//, ''));
    if (faktyczna !== p.sha256) bledy.push(`${gdzie}: SHA-256 pliku ${faktyczna} ≠ akty.json ${p.sha256}`);
    if (!zSums) bledy.push(`${gdzie}: brak wpisu w akty/SHA256SUMS`);
    else if (zSums !== p.sha256) bledy.push(`${gdzie}: SHA256SUMS ${zSums} ≠ akty.json ${p.sha256}`);
    if (bajty.length !== p.rozmiar) bledy.push(`${gdzie}: rozmiar ${bajty.length} B ≠ akty.json ${p.rozmiar} B`);
  }));
  return dostepne;
}

function czytajJson(sciezka, bledy) {
  try {
    return JSON.parse(readFileSync(sciezka, 'utf8'));
  } catch (e) {
    bledy.push(`${path.basename(sciezka)}: ${e.code === 'ENOENT' ? 'brak pliku' : `niepoprawny JSON (${e.message})`}`);
    return null;
  }
}

/**
 * @param {{katalog?: string|null, przyklad?: string, sprawdzSumy?: boolean}} opcje
 */
export function wczytajEksport(opcje = {}) {
  const katalog = opcje.katalog !== undefined ? opcje.katalog : (process.env.EKSPORT || (existsSync(path.join(SCIEZKA_EKSPORTU, 'manifest.json')) ? SCIEZKA_EKSPORTU : null));
  const sprawdzSumy = opcje.sprawdzSumy ?? process.env.SPRAWDZ_SUMY !== '0';
  const bledy = [];
  const ostrzezenia = [];
  let dane;

  if (katalog) {
    const k = path.resolve(katalog);
    dane = {
      tryb: 'paczka',
      katalog: k,
      manifest: czytajJson(path.join(k, 'manifest.json'), bledy),
      korzysci: czytajJson(path.join(k, 'korzysci.json'), bledy),
      akty: czytajJson(path.join(k, 'akty.json'), bledy),
      slowniki: czytajJson(path.join(k, 'slowniki.json'), bledy),
    };
    if (bledy.length) throw new BladEksportu(bledy);
  } else {
    const plik = opcje.przyklad ?? process.env.PRZYKLAD ?? SCIEZKA_PRZYKLADU;
    const surowe = czytajJson(plik, bledy);
    if (bledy.length) throw new BladEksportu(bledy);
    dane = { tryb: 'przyklad', katalog: null, ...surowe };
    delete dane._opis;
    for (const pole of ['manifest', 'korzysci', 'akty', 'slowniki']) {
      if (dane[pole] === undefined) bledy.push(`przyklad_eksportu.json: brak sekcji „${pole}”`);
    }
    if (bledy.length) throw new BladEksportu(bledy);
  }

  waliduj('Manifest', dane.manifest, 'manifest', bledy);
  if (!Array.isArray(dane.korzysci)) bledy.push('korzysci: oczekiwano listy rekordów');
  else dane.korzysci.forEach((k, i) => waliduj('Korzysc', k, `korzysci[${i}]${k?.id ? ` (${k.id})` : ''}`, bledy));
  if (!Array.isArray(dane.akty)) bledy.push('akty: oczekiwano listy rekordów');
  else dane.akty.forEach((a, i) => waliduj('Akt', a, `akty[${i}]${a?.eli ? ` (${a.eli})` : ''}`, bledy));
  waliduj('Slowniki', dane.slowniki, 'slowniki', bledy);
  if (bledy.length) throw new BladEksportu(bledy);

  sprawdzSpojnosc(dane, bledy, ostrzezenia);
  dane.plikiDostepne = dane.tryb === 'paczka'
    ? sprawdzPliki(dane.katalog, dane.manifest, dane.akty, sprawdzSumy, bledy, path.resolve(dane.katalog) === SCIEZKA_EKSPORTU)
    : new Set();
  if (bledy.length) throw new BladEksportu(bledy);

  dane.ostrzezenia = ostrzezenia;
  dane.sprawdzSumy = sprawdzSumy;
  return dane;
}

let pamiec = null;
/** Jedno wczytanie na proces budowania. */
export function eksport() {
  if (!pamiec) {
    pamiec = wczytajEksport();
    pamiec.ostrzezenia.forEach((o) => console.warn(`[eksport] ostrzeżenie: ${o}`));
  }
  return pamiec;
}
