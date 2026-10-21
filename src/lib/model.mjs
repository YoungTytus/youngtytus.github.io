// Widoki na dane eksportu używane przez strony. Tylko wyszukiwanie i grupowanie rekordów.
import { readFileSync } from 'node:fs';
import { eksport, sha256 } from './eksport.mjs';
import { czyData, liczbaZKwoty, posortujPliki } from './format.mjs';

export const dane = () => eksport();

export const korzyscPoId = (id) => dane().korzysci.find((k) => k.id === id) ?? null;
export const aktPoEli = (eli) => dane().akty.find((a) => a.eli === eli) ?? null;
export const etykieta = (slownik, kod) => dane().slowniki[slownik]?.[kod] ?? kod;

export const KOLEJNOSC_STATUSU = { obowiazuje: 0, do_ustalenia: 1, zamknieta: 2 };
export const posortowaneKorzysci = (lista = dane().korzysci) =>
  [...lista].sort((a, b) => KOLEJNOSC_STATUSU[a.status] - KOLEJNOSC_STATUSU[b.status] || a.nazwa.localeCompare(b.nazwa, 'pl'));

/** Źródła wyliczenia, także zagnieżdżonej podstawy i zasad zaokrąglania. */
export function dowodyWyliczenia(wyliczenie) {
  const dowody = [];
  const odwiedz = (v) => {
    if (!v || typeof v !== 'object') return;
    if (v.eli && v.przepis && v.cytat) { dowody.push(v); return; }
    Object.values(v).forEach(odwiedz);
  };
  odwiedz(wyliczenie);
  return dowody;
}

/** Gotowy wynik eksportu. Nie wykonujemy obliczeń ani nie zastępujemy kwoty bezpośredniej. */
export function kwotaPrezentowana(k) {
  const w = k.ile.wyliczenie;
  return k.ile.aktualna ?? (w?.wartosc || w?.warianty?.length ? w : null);
}

export const czyKwotaWyliczona = (k) => !k.ile.aktualna && kwotaPrezentowana(k) !== null;

/**
 * Limit kwoty z przepisu (np. „nie może być wyższa niż kryterium dochodowe”) na dzień eksportu.
 * Pokazywany tylko, gdy karta nie ma kwoty aktualnej ani wyliczenia. Wpis wybiera pipeline datami od–do.
 */
export function limitPrezentowany(k, dzien = dataEksportu()) {
  if (kwotaPrezentowana(k)) return null;
  for (const [pi, p] of (k.ile.progi ?? []).entries()) {
    const i = p.wpisy.findIndex((w) => w._rodzaj && w.wartosc && w.od && (!dzien || (w.od <= dzien && (!w.do || w.do >= dzien))));
    if (i >= 0) return { ...p.wpisy[i], przepis: p.przepis, href: `#prog-${pi}-${i}`, etykieta: `${p.wpisy[i].dowod.eli} · ${p.wpisy[i].dowod.przepis}` };
  }
  return null;
}

/** Na stronie głównej najpierw karty z kwotą (aktualną, wyliczoną albo limitem), potem pozostałe. */
export const wyroznioneKorzysci = (n = 6) => {
  const zKwota = (k) => (kwotaPrezentowana(k) ? 0 : limitPrezentowany(k) ? 1 : 2);
  return posortowaneKorzysci().sort((a, b) => zKwota(a) - zKwota(b)).slice(0, n);
};

/** Akty ze wszystkich dowodów korzyści. Kolejność pierwszego wystąpienia. */
export function elisKorzysci(k) {
  const lista = [k.przepis.eli, ...k.ile.trasa.map((t) => t.dowod.eli), ...k.ile.os_czasu.map((w) => w.dowod.eli),
    ...k.do_kiedy.map((t) => t.dowod.eli), ...k.do_kiedy.flatMap((t) => (t.etapy ?? []).map((e) => e.dowod.eli)),
    ...(k.ile.progi ?? []).flatMap((p) => p.wpisy.map((w) => w.dowod.eli)),
    ...(k.ile.zwiekszenia ?? []).flatMap((z) => [z.dowod?.eli, z.dowod_limitu?.eli]),
    ...dowodyWyliczenia(k.ile.wyliczenie).map((d) => d.eli)];
  return [...new Set(lista.filter(Boolean))];
}

/** Akty, których pliki pokazuje karta korzyści (SPEC 5.7, zasada 4). */
export function aktyDoPobrania(k) {
  return elisKorzysci(k).map((eli) => {
    const akt = aktPoEli(eli);
    return { eli, akt, pliki: akt ? posortujPliki(akt.pliki) : [] };
  });
}

/**
 * Wpis osi czasu, który dokumentuje bieżącą kwotę: ten sam napis (albo te same warianty) i ta sama data "od".
 * To dopasowanie rekordów, nie wybór kwoty: kwotę wskazuje pipeline polem ile.aktualna.
 */
export function indeksWpisuAktualnej(k) {
  const a = k.ile.aktualna;
  if (!a) return -1;
  const klucz = (w) => JSON.stringify([w.wartosc ?? null, (w.warianty ?? []).map((x) => [x.etykieta, x.wartosc])]);
  const kA = klucz(a);
  const idx = k.ile.os_czasu.findIndex((w) => klucz(w) === kA && (w.od ?? null) === (a.od ?? null));
  return idx;
}

export function dowodAktualnej(k) {
  if (czyKwotaWyliczona(k)) return { href: '#wyliczenie', etykieta: 'Wyliczenie i źródła', dowod: null };
  const i = indeksWpisuAktualnej(k);
  if (i >= 0) return { href: `#wpis-${i}`, etykieta: `${k.ile.os_czasu[i].dowod.eli} · ${k.ile.os_czasu[i].dowod.przepis}`, dowod: k.ile.os_czasu[i].dowod };
  const ostatni = k.ile.trasa.at(-1);
  if (ostatni) return { href: '#zrodla', etykieta: `${ostatni.dowod.eli} · ${ostatni.dowod.przepis}`, dowod: ostatni.dowod };
  return { href: '#przepis', etykieta: `${k.przepis.eli} · ${k.przepis.przepis}`, dowod: k.przepis };
}

/** Sortowanie potwierdzonych kwot; wyliczenia pomocnicze, warianty i braki trafiają na koniec. */
export const kwotaDoSortowania = (k) => liczbaZKwoty(k.ile.aktualna?.wartosc);

export function indeksWyszukiwania() {
  return dane().korzysci.map((k) => ({
    id: k.id,
    nazwa: k.nazwa,
    rodzaj: k.rodzaj_korzysci,
    status: k.status,
    sytuacje: k.sytuacje,
    akt: k.przepis.eli,
    kwota: kwotaDoSortowania(k),
    tekst: [k.nazwa, k.komu, k.opis_prosty, k.przepis.eli, k.przepis.przepis, k.przepis.cytat,
      ...k.ile.trasa.map((t) => `${t.opis} ${t.dowod.cytat}`),
      ...k.sytuacje.map((s) => etykieta('sytuacje', s)),
      aktPoEli(k.przepis.eli)?.tytul].filter(Boolean).join(' '),
  }));
}

export const liczbaWSytuacji = (kod) => dane().korzysci.filter((k) => k.sytuacje.includes(kod)).length;

/** Akty, w których dany akt jest wymieniony jako wykonawczy. */
export const aktyNadrzedne = (eli) => dane().akty.filter((a) => a.wykonawcze.some((w) => w.eli === eli));

// ---------- pliki do pobrania w /dane ----------

const csvPole = (v) => {
  const s = v == null ? '' : String(v);
  return /[";\n,]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s;
};

/** Historia kwot w CSV: jeden wiersz na wpis i wariant, wartości jako napisy źródłowe. */
export function historiaCsv(lista = dane().korzysci) {
  const naglowek = ['id_korzysci', 'nazwa', 'wariant', 'wartosc', 'od', 'do', 'rodzaj_zmiany', 'poprzednia',
    'roznica_kwota', 'roznica_procent', 'dowod_eli', 'dowod_przepis', 'dowod_url'];
  const wiersze = [naglowek];
  for (const k of lista) {
    for (const w of k.ile.os_czasu) {
      const warianty = w.warianty?.length ? w.warianty : [{ etykieta: '', wartosc: w.wartosc }];
      for (const v of warianty) {
        wiersze.push([k.id, k.nazwa, v.etykieta, v.wartosc, w.od, w.do, w.rodzaj_zmiany, Array.isArray(w.poprzednia) ? w.poprzednia.join(' / ') : w.poprzednia,
          w.roznica?.kwota, w.roznica?.procent, w.dowod.eli, w.dowod.przepis, w.dowod.url]);
      }
    }
  }
  return '﻿' + wiersze.map((r) => r.map(csvPole).join(',')).join('\r\n') + '\r\n';
}

const json = (v) => JSON.stringify(v, null, 1) + '\n';

/** Pliki serwowane w /dane/: nazwa → treść. W trybie paczki to dokładne bajty z paczki. */
export function plikiDanych() {
  const d = dane();
  const pliki = new Map();
  if (d.tryb === 'paczka') {
    for (const n of ['manifest.json', 'korzysci.json', 'akty.json', 'slowniki.json']) {
      pliki.set(n, readFileSync(`${d.katalog}/${n}`));
    }
    if (d.manifest.pliki?.['socjal.json']) pliki.set('socjal.json', readFileSync(`${d.katalog}/socjal.json`));
    pliki.set('SHA256SUMS', readFileSync(`${d.katalog}/akty/SHA256SUMS`));
  } else {
    pliki.set('manifest.json', Buffer.from(json(d.manifest)));
    pliki.set('korzysci.json', Buffer.from(json(d.korzysci)));
    pliki.set('akty.json', Buffer.from(json(d.akty)));
    pliki.set('slowniki.json', Buffer.from(json(d.slowniki)));
  }
  pliki.set('historia_kwot.csv', Buffer.from(historiaCsv()));
  return [...pliki].map(([nazwa, bajty]) => ({ nazwa, bajty, sha256: sha256(bajty), rozmiar: bajty.length }));
}

export const dataEksportu = () => {
  const w = dane().manifest.wygenerowano;
  return czyData(w.slice(0, 10)) ? w.slice(0, 10) : null;
};
