// Walidacja eksportu przed budowaniem. Kod wyjścia 1 = budowanie przerwane.
import { wczytajEksport, BladEksportu } from '../src/lib/eksport.mjs';

try {
  const d = wczytajEksport();
  d.ostrzezenia.forEach((o) => console.warn(`ostrzeżenie: ${o}`));
  const zrodlo = d.tryb === 'paczka' ? `paczka ${d.katalog}` : 'plik przykładowy (bez PDF, sumy plików aktów nie są sprawdzane)';
  console.log(`Eksport poprawny: ${d.korzysci.length} korzyści, ${d.akty.length} aktów, kontrakt ${d.manifest.kontrakt}; ${zrodlo}.`);
  if (d.tryb === 'paczka' && !d.sprawdzSumy) console.warn('UWAGA: SPRAWDZ_SUMY=0, sumy SHA-256 plików aktów pominięte (dozwolone tylko na etapach S1–S3).');
} catch (e) {
  if (e instanceof BladEksportu) { console.error(e.message); process.exit(1); }
  throw e;
}
