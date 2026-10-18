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
