// Wyszukiwanie po stronie klienta: bez polskich znaków, dopasowanie rdzenia (początek słowa).
// Ten sam kod działa w przeglądarce i w testach.
export const normalizuj = (s) =>
  String(s ?? '').toLocaleLowerCase('pl').replace(/ł/g, 'l').normalize('NFD').replace(/[\u0300-\u036f]/g, '');

/** Rdzeń: dla słów dłuższych niż 4 litery obcinamy końcówkę (do 3 znaków), zostaje min. 4. */
export const rdzen = (slowo) => (slowo.length > 4 ? slowo.slice(0, Math.max(4, slowo.length - 3)) : slowo);

export function pasuje(tekst, zapytanie) {
  const slowa = normalizuj(tekst).split(/[^a-z0-9]+/).filter(Boolean);
  const terminy = normalizuj(zapytanie).split(/[^a-z0-9]+/).filter(Boolean);
  return terminy.every((t) => {
    const r = rdzen(t);
    return slowa.some((s) => s.startsWith(r));
  });
}

/**
 * Trafność rekordu indeksu (0 = nie pasuje). Nazwa > opis i „komu” > treść przepisów i tytuł aktu.
 * Treść przepisów liczy się tylko wtedy, gdy nic nie pasuje w nazwie ani opisie (zob. szukaj()):
 * inaczej „renta” zwracała każdą kartę z ustawy „o emeryturach i rentach”.
 */
export function ocena(r, zapytanie) {
  if (!normalizuj(zapytanie).trim()) return 1;
  if (pasuje(r.nazwa, zapytanie)) {
    // całe słowo zapytania w nazwie (nie tylko rdzeń) podnosi wynik, np. „zasiłek rodzinny”
    const nazwa = normalizuj(r.nazwa).split(/[^a-z0-9]+/);
    const terminy = normalizuj(zapytanie).split(/[^a-z0-9]+/).filter(Boolean);
    const cale = terminy.filter((t) => nazwa.some((s) => s.startsWith(t))).length / terminy.length;
    // nazwa zaczynająca się od pierwszego słowa zapytania („Renta rodzinna” przed „Emerytura lub renta…”)
    return 3 + cale + (nazwa[0]?.startsWith(rdzen(terminy[0])) ? 0.5 : 0);
  }
  if (pasuje(r.glowny, zapytanie)) return 2;
  if (pasuje(r.tekst, zapytanie)) return 1;
  return 0;
}

/** Rekordy pasujące do zapytania, od najtrafniejszych; treść przepisów tylko jako ostatnia deska ratunku. */
export function szukaj(indeks, zapytanie) {
  const oceny = indeks.map((r) => [r, ocena(r, zapytanie)]).filter(([, o]) => o > 0);
  const mocne = oceny.filter(([, o]) => o >= 2);
  return { wyniki: mocne.length ? mocne : oceny, wTresci: !mocne.length && oceny.length > 0 && !!normalizuj(zapytanie).trim() };
}
