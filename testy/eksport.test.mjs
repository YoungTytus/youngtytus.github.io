// Testy kontraktu danych i wyszukiwarki (SPEC 10: S1, S2, S4).
// Uruchom: npm test
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { BladEksportu, sha256, wczytajEksport } from '../src/lib/eksport.mjs';
import { pasuje } from '../src/lib/szukaj.mjs';
import { dataPL, eliDziennik, liczbaZKwoty, typo } from '../src/lib/format.mjs';

const PRZYKLAD = path.resolve('data', 'przyklad_eksportu.json');
const przyklad = () => JSON.parse(readFileSync(PRZYKLAD, 'utf8'));
const tmp = () => mkdtempSync(path.join(tmpdir(), 'mapa-test-'));

function zapiszPrzyklad(dane) {
  const dir = tmp();
  const plik = path.join(dir, 'p.json');
  writeFileSync(plik, JSON.stringify(dane));
  return plik;
}

const oczekujBledu = (fn, ...fragmenty) => {
  assert.throws(fn, (e) => {
    assert.ok(e instanceof BladEksportu, `oczekiwano BladEksportu, jest ${e}`);
    for (const f of fragmenty) assert.match(e.message, f);
    return true;
  });
};

test('plik przykładowy przechodzi walidację', () => {
  const d = wczytajEksport({ katalog: null, przyklad: PRZYKLAD });
  assert.equal(d.korzysci.length, 3);
  assert.equal(d.tryb, 'przyklad');
});

test('S1: walidacja odrzuca brak wymaganego pola i wskazuje rekord', () => {
  const d = przyklad();
  delete d.korzysci[1].nazwa;
  oczekujBledu(() => wczytajEksport({ katalog: null, przyklad: zapiszPrzyklad(d) }), /korzysci\[1\] \(DU-2003-2255-art6\)/, /nazwa/);
});

test('S1: walidacja odrzuca nieznany status', () => {
  const d = przyklad();
  d.korzysci[0].status = 'aktywna';
  oczekujBledu(() => wczytajEksport({ katalog: null, przyklad: zapiszPrzyklad(d) }), /\/status/, /obowiazuje/);
});

test('S1: walidacja odrzuca źle posortowaną oś czasu', () => {
  const d = przyklad();
  d.korzysci[1].ile.os_czasu.reverse();
  oczekujBledu(() => wczytajEksport({ katalog: null, przyklad: zapiszPrzyklad(d) }), /os_czasu/);
});

test('S1: walidacja odrzuca nazwę pobierania spoza [A-Za-z0-9_.-]', () => {
  const d = przyklad();
  d.akty[0].pliki[0].nazwa_pobierania = 'ustawa o rencie.pdf';
  oczekujBledu(() => wczytajEksport({ katalog: null, przyklad: zapiszPrzyklad(d) }), /nazwa_pobierania/);
});

test('termin bez rodzaju jest pomijany i zgłaszany, nie przerywa budowania', () => {
  const d = przyklad();
  delete d.korzysci[2].do_kiedy[0].rodzaj;
  const w = wczytajEksport({ katalog: null, przyklad: zapiszPrzyklad(d) });
  assert.equal(w.korzysci[2].do_kiedy.length, 0);
  assert.match(w.ostrzezenia.join('\n'), /bez pola „rodzaj”/);
});

// ---------- tryb paczki: sumy SHA-256 (S4) ----------

function zbudujPaczke() {
  const d = przyklad();
  const dir = tmp();
  const sumy = [];
  for (const a of d.akty) {
    for (const p of a.pliki) {
      const bajty = Buffer.from(`%PDF-1.4\n% zaslepka ${p.plik}\n%%EOF\n`);
      mkdirSync(path.dirname(path.join(dir, p.plik)), { recursive: true });
      writeFileSync(path.join(dir, p.plik), bajty);
      p.sha256 = sha256(bajty);
      p.rozmiar = bajty.length;
      sumy.push(`${p.sha256}  ${p.plik.replace(/^akty\//, '')}`);
    }
  }
  const pliki = {
    'korzysci.json': JSON.stringify(d.korzysci),
    'akty.json': JSON.stringify(d.akty),
    'slowniki.json': JSON.stringify(d.slowniki),
    'akty/SHA256SUMS': sumy.join('\n') + '\n',
  };
  const manifest = { ...d.manifest, pliki: {} };
  for (const [n, tresc] of Object.entries(pliki)) {
    writeFileSync(path.join(dir, n), tresc);
    manifest.pliki[n] = sha256(Buffer.from(tresc));
  }
  writeFileSync(path.join(dir, 'manifest.json'), JSON.stringify(manifest));
  return { dir, d };
}

test('S4: poprawna paczka przechodzi, wszystkie pliki aktów są dostępne', () => {
  const { dir, d } = zbudujPaczke();
  const w = wczytajEksport({ katalog: dir, sprawdzSumy: true });
  assert.equal(w.plikiDostepne.size, d.akty.reduce((s, a) => s + a.pliki.length, 0));
  rmSync(dir, { recursive: true });
});

test('S4: podmiana jednego bajtu PDF przerywa budowanie', () => {
  const { dir, d } = zbudujPaczke();
  const plik = path.join(dir, d.akty[0].pliki[0].plik);
  const bajty = readFileSync(plik);
  bajty[bajty.length - 2] ^= 1;
  writeFileSync(plik, bajty);
  oczekujBledu(() => wczytajEksport({ katalog: dir, sprawdzSumy: true }), /SHA-256 pliku/, /DU_2003_1268/);
  rmSync(dir, { recursive: true });
});

test('S4: brak pliku aktu w paczce przerywa budowanie', () => {
  const { dir, d } = zbudujPaczke();
  rmSync(path.join(dir, d.akty[3].pliki[0].plik));
  oczekujBledu(() => wczytajEksport({ katalog: dir, sprawdzSumy: true }), /nie istnieje w paczce/);
  rmSync(dir, { recursive: true });
});

test('S4: plik danych niezgodny z manifestem przerywa budowanie', () => {
  const { dir } = zbudujPaczke();
  writeFileSync(path.join(dir, 'slowniki.json'), readFileSync(path.join(dir, 'slowniki.json'), 'utf8') + ' ');
  oczekujBledu(() => wczytajEksport({ katalog: dir, sprawdzSumy: true }), /slowniki\.json: SHA-256/);
  rmSync(dir, { recursive: true });
});

// ---------- wyszukiwarka (S2) ----------

test('S2: „dodatek dopełniający” i „renta” znajdują właściwe karty', () => {
  const d = wczytajEksport({ katalog: null, przyklad: PRZYKLAD });
  const tekst = (k) => [k.nazwa, k.komu, k.przepis.cytat].join(' ');
  const szukaj = (q) => d.korzysci.filter((k) => pasuje(tekst(k), q)).map((k) => k.slug);
  assert.deepEqual(szukaj('dodatek dopełniający'), ['dodatek-dopelniajacy']);
  assert.deepEqual(szukaj('renta'), ['dodatek-dopelniajacy']);
  assert.deepEqual(szukaj('dodatek weglowy'), ['dodatek-weglowy']);
  assert.deepEqual(szukaj('ZASIŁKU rodzinnego'), ['zasilek-rodzinny']);
});

// ---------- formatowanie ----------

test('formatowanie dat, kwot i oznaczeń dzienników', () => {
  assert.equal(dataPL('2026-03-01'), '1 marca 2026 r.');
  assert.equal(eliDziennik('MP/2026/153'), 'M.P. 2026 poz. 153');
  assert.equal(liczbaZKwoty('2704,71 zł'), 2704.71);
  assert.equal(liczbaZKwoty('3000 złotych'), 3000);
  assert.equal(liczbaZKwoty('77,00 zł / 106,00 zł'), null);
  assert.equal(typo('art. 6a ust. 1, 2520 zł'), 'art. 6a ust. 1, 2520 zł');
});
