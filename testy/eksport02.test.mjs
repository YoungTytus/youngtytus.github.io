import { test } from 'node:test';
import assert from 'node:assert/strict';
import { wczytajEksport } from '../src/lib/eksport.mjs';
import { etykietaWariantu, KOLEJNOSC_TERMINOW, typo } from '../src/lib/format.mjs';
test('bieżący eksport: manifest, liczby i odnośniki PDF', () => {
 const d = wczytajEksport();
 assert.equal(d.tryb, 'paczka');
 assert.ok(['strona-0.2', 'strona-0.3', 'strona-0.4'].includes(d.manifest.kontrakt));
 assert.equal(d.korzysci.length, d.manifest.liczby.korzysci);
 assert.equal(d.akty.length, d.manifest.liczby.akty);
 assert.equal(d.akty.flatMap(a => a.pliki).length, d.manifest.liczby.pliki_aktow);
 assert.equal(d.plikiDostepne.size, 0);
});
test('brak etykiety i tablice poprzednich kwot są obsługiwane', () => {
 assert.equal(etykietaWariantu({etykieta:null},1), 'Wariant 2 (opis nieustalony)');
 assert.equal(typo(['77,00 zł','106,00 zł']), '77,00\u00a0zł / 106,00\u00a0zł');
 assert.ok(KOLEJNOSC_TERMINOW.includes('termin_wyplaty'));
});
