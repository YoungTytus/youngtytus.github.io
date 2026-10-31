// Formatowanie do wyświetlenia. Nic tu nie wylicza wartości prawnych:
// zmienia tylko zapis (daty, twarde spacje, etykiety) danych z eksportu.

const MIESIACE = ['stycznia', 'lutego', 'marca', 'kwietnia', 'maja', 'czerwca', 'lipca',
  'sierpnia', 'września', 'października', 'listopada', 'grudnia'];
const NBSP = ' ';

export const czyData = (v) => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v);
export const czyZaslepka = (v) => typeof v === 'string' && v.startsWith('_do_ustalenia_');
/** Etap pipeline'u z zaślepki, np. "_do_ustalenia_E5" → "E5". */
export const etapZaslepki = (v) => (czyZaslepka(v) ? v.replace('_do_ustalenia_', '') : null);

/** "2026-03-01" → "1 marca 2026 r." (dzień bez zera wiodącego, z twardymi spacjami). */
export function dataPL(v) {
  if (!czyData(v)) return null;
  const [r, m, d] = v.split('-').map(Number);
  return `${d}${NBSP}${MIESIACE[m - 1]}${NBSP}${r}${NBSP}r.`;
}

/** Data albo jawny brak. */
export function dataLubBrak(v, brak = 'nie ustalono') {
  if (czyData(v)) return dataPL(v);
  if (czyZaslepka(v)) return `${brak} (etap ${etapZaslepki(v)})`;
  return brak;
}

/** Twarde spacje w typowych miejscach polskiej typografii prawniczej. Nie zmienia znaków widocznych. */
/**
 * Jeden zapis kwoty na całej stronie: „1 978,49 zł” (spacja tysięcy niełamliwa, zawsze grosze, „zł”).
 * Tylko dla wyświetlanych kwot — cytaty przepisów zostają dosłowne („3000 złotych”).
 */
export function kwotaPL(s) {
  if (s == null) return s;
  if (Array.isArray(s)) return s.map(kwotaPL).join(' / ');
  return String(s).replace(/(\d{1,3}(?:[  ]\d{3})+|\d+)(?:[.,](\d{1,2}))?\s*(?:zł|złotych|złote|złoty)(?!\p{L})/gu, (m, cale, gr) => {
    const tys = cale.replace(/[  ]/g, '').replace(/\B(?=(\d{3})+(?!\d))/g, NBSP);
    return `${tys},${(gr ?? '00').padEnd(2, '0')}${NBSP}zł`;
  });
}

export function typo(s) {
  if (s == null) return s;
  if (Array.isArray(s)) return s.map(typo).join(' / ');
  return String(s)
    .replace(/(\d) (zł|złotych|gr)(?!\p{L})/gu, `$1${NBSP}$2`)
    .replace(/\b(art|ust|pkt|lit|poz|nr)\. (?=[\d§])/g, `$1.${NBSP}`)
    .replace(/§ (?=\d)/g, `§${NBSP}`)
    .replace(/(\d) %/g, `$1${NBSP}%`)
    .replace(/ ([wizaou]) /gi, ` $1${NBSP}`);
}

/** "DU/2003/1268" → "Dz.U. 2003 poz. 1268". */
export function eliDziennik(eli) {
  const m = /^(DU|MP)\/(\d{4})\/(\d+)$/.exec(eli ?? '');
  if (!m) return eli;
  return `${m[1] === 'DU' ? 'Dz.U.' : 'M.P.'} ${m[2]} poz.${NBSP}${m[3]}`;
}

/** "DU/2003/1268" → "DU-2003-1268" (adres strony aktu). */
export const eliSlug = (eli) => eli.replaceAll('/', '-');

/** "2704,71 zł" → 2704.71, tylko na potrzeby osi wykresu. Napis złożony (np. "77 / 106") → null. */
export function liczbaZKwoty(s) {
  if (typeof s !== 'string' || s.includes('/')) return null;
  const czysty = s.replace(/[^\d,.-]/g, '').replace(/\.(?=\d{3}\b)/g, '').replace(',', '.');
  if (!/^-?\d+(\.\d+)?$/.test(czysty)) return null;
  return Number(czysty);
}

export function rozmiar(b) {
  if (b < 1024) return `${b}${NBSP}B`;
  if (b < 1024 * 1024) return `${Math.round(b / 1024)}${NBSP}KB`;
  return `${(b / 1024 / 1024).toFixed(1).replace('.', ',')}${NBSP}MB`;
}

const KOLEJNOSC_PLIKOW = { U: 0, TJ: 1, O: 2 };
export const posortujPliki = (pliki) => [...pliki].sort((a, b) => KOLEJNOSC_PLIKOW[a.rodzaj] - KOLEJNOSC_PLIKOW[b.rodzaj]);

/** Etykieta pliku według rodzaju (SPEC 5.7, zasada 1). */
export function etykietaPliku(p, akt) {
  if (p.rodzaj === 'U') {
    return { nazwa: 'Tekst ujednolicony', opis: `stan prawny na ${dataPL(p.data_stanu)} (informacyjny)`, moc: 'informacyjny' };
  }
  if (p.rodzaj === 'TJ') {
    return {
      nazwa: 'Tekst jednolity',
      opis: `ogłoszony ${p.eli_obwieszczenia ? eliDziennik(p.eli_obwieszczenia) : ''}, wiążący; zmiany po tej dacie zawiera tekst ujednolicony`,
      moc: 'wiążący',
    };
  }
  const dopisek = akt?.typ === 'Ustawa' && akt.pliki.some((x) => x.rodzaj === 'U') ? '; nie uwzględnia późniejszych zmian' : '';
  return {
    nazwa: 'Tekst ogłoszony',
    opis: `${eliDziennik(akt?.eli ?? '')} (wiążący, brzmienie pierwotne z dnia ogłoszenia${dopisek})`,
    moc: 'wiążący',
  };
}

export const etykietaZmiany = {
  waloryzacja: 'waloryzacja',
  bez_zmiany_kwoty: 'bez zmiany kwoty',
  pierwszy_znany_wpis: 'pierwszy znany wpis',
  nowelizacja: 'nowelizacja',
  akt_wykonawczy: 'akt wykonawczy',
  brzmienie_pierwotne: 'brzmienie pierwotne',
};

/** Forma świadczenia (art. 36 ustawy o pomocy społecznej: pieniężne i niepieniężne). */
export const etykietaFormy = {
  pieniezne: 'pieniężne',
  niepieniezne: 'niepieniężne (rzecz, usługa, miejsce)',
  nieustalona: 'forma nieustalona',
};

export const etykietaRozwiazania = {
  kwota_w_ustawie: 'kwota wprost w ustawie',
  kwota_z_aktu_wykonawczego: 'kwota z aktu wykonawczego',
  regula_procentowa: 'reguła procentowa',
  formula: 'formuła lub zasada ustalania wysokości',
  odeslanie: 'odesłanie do innego przepisu',
  nieustalone: 'nie ustalono',
};

export const KOLEJNOSC_TERMINOW = ['okres_kwoty', 'termin_wniosku', 'granica_przepisu', 'okres_zasilkowy', 'harmonogram_dostepnosci', 'termin_wyplaty', 'termin_dokumentu', 'termin_organu', 'termin_inny', 'wejscie_w_zycie'];

export const OPIS_TERMINU = {
  termin_dokumentu: 'Termin dostarczenia dokumentów wskazanych w przepisie.',
  termin_organu: 'Termin czynności organu wskazany w danych źródłowych.',
  termin_inny: 'Pozostały termin: znaczenie wynika z cytowanego przepisu.',
  wejscie_w_zycie: 'Data wejścia w życie wskazana w danych źródłowych.',
  okres_kwoty: 'Od kiedy do kiedy obowiązuje dana kwota.',
  termin_wniosku: 'Do kiedy złożyć wniosek i co się dzieje po terminie.',
  granica_przepisu: 'Od kiedy albo do kiedy obowiązuje sam przepis lub jego brzmienie.',
  okres_zasilkowy: 'Cykl, na który przyznaje się świadczenie.',
  harmonogram_dostepnosci: 'Prawo otwierane etapami, np. dla kolejnych grup.',
  termin_wyplaty: 'Do kiedy organ wypłaca świadczenie, licząc od wskazanego zdarzenia.',
};

export const wielka = (s) => (s ? s.charAt(0).toLocaleUpperCase('pl') + s.slice(1) : s);
/** „Ustawa z dnia 12 marca 2004 r. o pomocy społecznej” → „O pomocy społecznej”; kodeksy zostają z nazwą. */
export function krotkiTytul(tytul, eli) {
  const t = String(tytul ?? '').replace(/^\s*(?:ustawa|rozporządzenie|obwieszczenie)\s+z\s+dnia\s+\d{1,2}\s+\S+\s+\d{4}\s*r\.\s*[–-]?\s*/i, '').replace(/\.$/, '').trim();
  return t ? wielka(t) : eli;
}
export const etykietaWariantu = (w, i) => w.etykieta ?? `Wariant ${i + 1} (opis nieustalony)`;
export const opisUprawnionych = (s) => typeof s === 'string' && /\p{L}/u.test(s) ? s : 'Krąg uprawnionych nie został opisany w eksporcie. Zobacz cytat przepisu na karcie.';

/** Etykieta dowodu: "MP/2026/153 · komunikat". */
export const etykietaDowodu = (d) => `${d.eli} · ${d.przepis}`;
