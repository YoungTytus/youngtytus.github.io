import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { BladEksportu, wczytajEksport } from '../src/lib/eksport.mjs';
import { czyKwotaWyliczona, dowodAktualnej, elisKorzysci, historiaCsv, kwotaPrezentowana, kwotaDoSortowania } from '../src/lib/model.mjs';

const baza = () => JSON.parse(readFileSync('data/przyklad_eksportu.json', 'utf8'));
const dowod = (eli) => ({ eli, przepis: 'tresc', cytat: 'Kwota bazowa ogłoszona w komunikacie.', url: `https://api.sejm.gov.pl/eli/acts/${eli}`, data_stanu: null });
const wynik = () => ({
  wartosc: '999,00 zł', warianty: null, od: '2026-03-01',
  podstawa: { wartosc: '1978,49 zł', od: '2026-03-01', zrodlo: 'MP/2026/220', wielkosc: null, dowod: dowod('MP/2026/220'), lancuch: null },
  zaokraglenie: null, uwaga: 'Wynik dostarczony w eksporcie.', flagi: [], nieustalone: [],
});
function rekord() {
  const k = baza().korzysci[0];
  k.ile.aktualna = null;
  k.ile.regula = { udzial: '50 %', podstawa_id: null, opis: 'kwoty bazowej' };
  k.ile.rozwiazanie = 'regula_procentowa';
  k.ile.wyliczenie = wynik();
  return k;
}
function walidujRekord(k) {
  const dir = mkdtempSync(path.join(tmpdir(), 'mapa-p1-'));
  try {
    const d = baza(); d.korzysci[0] = k;
    const file = path.join(dir, 'p.json'); writeFileSync(file, JSON.stringify(d));
    return wczytajEksport({ katalog: null, przyklad: file });
  } finally { rmSync(dir, { recursive: true, force: true }); }
}

test('gotowy wynik jest pokazany bez ponownego liczenia i bez dopisania do historii', () => {
  const k = rekord(), przed = JSON.stringify(k), csv = historiaCsv([k]);
  // Umyślnie wynik nie jest równy 50% podstawy: witryna ma przenieść bajty, nie poprawiać prawa.
  assert.equal(kwotaPrezentowana(k).wartosc, '999,00 zł');
  assert.equal(kwotaDoSortowania(k), null);
  assert.equal(czyKwotaWyliczona(k), true);
  assert.equal(dowodAktualnej(k).href, '#wyliczenie');
  assert.equal(historiaCsv([k]), csv);
  assert.equal(JSON.stringify(k), przed);
  k.ile.aktualna = { wartosc: '100,00 zł', od: null };
  assert.equal(kwotaPrezentowana(k).wartosc, '100,00 zł');
  assert.equal(czyKwotaWyliczona(k), false);
  delete k.ile.wyliczenie; k.ile.aktualna = null;
  assert.equal(kwotaPrezentowana(k), null);
});

test('akty do pobrania obejmują zagnieżdżoną podstawę, zaokrąglanie i oddzielny limit', () => {
  const k = rekord(), w = wynik();
  k.ile.wyliczenie.podstawa.dowod = null;
  k.ile.wyliczenie.podstawa.lancuch = w;
  k.ile.wyliczenie.zaokraglenie = { regula: 'w górę', dowod: dowod('DU/2023/1429') };
  k.ile.zwiekszenia = [{ dowod: k.przepis, dowod_limitu: dowod('DU/2024/1238') }];
  const elis = elisKorzysci(k);
  for (const eli of ['MP/2026/220', 'DU/2023/1429', 'DU/2024/1238']) assert.ok(elis.includes(eli));
  assert.equal(elis.length, new Set(elis).size);
});

test('P1: puste komu i nieopisane warianty są brakami, uszkodzony dowód zatrzymuje import', () => {
  const k = rekord(); k.komu = '';
  k.ile.regula = { udzial: null, podstawa_id: null, opis: 'kwoty bazowej', warianty: [{ etykieta: null, udzial: '50 %' }] };
  assert.doesNotThrow(() => walidujRekord(k));
  k.ile.wyliczenie.podstawa.lancuch = wynik();
  delete k.ile.wyliczenie.podstawa.lancuch.podstawa.dowod.cytat;
  assert.throws(() => walidujRekord(k), e => e instanceof BladEksportu && /lancuch.*dowod.*cytat/s.test(e.message));
});
