// Dane podstrony /liczby/ z data/liczby/liczby.json (eksport projektu Raport_Socjal_Wydatki,
// skrypt Skrypty/eksport_liczby_json.py). Strona nie wpisuje liczb ręcznie: wszystko, co
// pokazuje, jest polem pliku albo prostym działaniem na polach (iloraz, suma, różnica).
import { createHash } from 'node:crypto';
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';

const KATALOG_STRONY = process.env.STRONA_KATALOG ?? process.cwd();
export const SCIEZKA_LICZB = path.resolve(KATALOG_STRONY, 'data', 'liczby', 'liczby.json');
const NBSP = ' ';

/** Nazwa województwa lub powiatu z wielkiej litery; „M.Białystok” (miasto na prawach powiatu) → „Białystok (miasto)”. */
export function nazwaJednostki(n) {
  const s = String(n ?? '').trim();
  const m = /^M\.\s*(.+)$/.exec(s);
  if (m) return `${m[1]} (miasto)`;
  return s ? s.charAt(0).toLocaleUpperCase('pl') + s.slice(1) : s;
}

/** Pola wymagane przez stronę (koncept v3); ta sama lista jest w aktualizuj_strone.py. */
export const POLA_LICZB = ['meta', 'licznik_2025', 'bez_emerytur_zus_2025', 'suma', 'platnicy_2022_2025_mld', 'programy',
  'na_mieszkanca', 'dzialy_budzetu', 'fundusz_solidarnosciowy', 'wojewodztwa', 'powiaty', 'fakty', 'jst_bilans_mld',
  'jst_rozdzialy_mld', 'udzialy_platnikow_2025_proc', 'przeplywy_budzetu_2025_mld', 'cofog10', 'kontrole'];

let pamiec = null;
/** Dane albo null, gdy pliku nie ma (wtedy strona /liczby/ nie powstaje). */
export function liczby() {
  if (pamiec !== null) return pamiec || null;
  if (!existsSync(SCIEZKA_LICZB)) { pamiec = false; return null; }
  const bajty = readFileSync(SCIEZKA_LICZB);
  const d = JSON.parse(bajty.toString('utf8'));
  const brak = POLA_LICZB.filter((k) => !(k in d));
  if (brak.length) throw new Error(`data/liczby/liczby.json: brak pól ${brak.join(', ')}`);
  d._sha256 = createHash('sha256').update(bajty).digest('hex');
  for (const x of [...d.wojewodztwa, ...d.powiaty]) x.nazwa = nazwaJednostki(x.nazwa);
  pamiec = d;
  return d;
}

// ---------- formaty (koncept v3: przecinek dziesiętny, twarda spacja w liczbach od 10 000 i przed
// jednostką oraz „%”, bez pauzy, półpauzy i znaku minus: brak wartości „-”, liczba ujemna z łącznikiem) ----------

export function liczba(v, miejsca = 0) {
  if (v == null || Number.isNaN(v)) return '-';
  // zaokrąglenie połówek w górę także dla 32,15 (toFixed daje 32,1 przez zapis binarny)
  const f = 10 ** miejsca;
  const [c, u] = (Math.round(Math.abs(v) * f * (1 + 1e-12)) / f).toFixed(miejsca).split('.');
  const cale = c.length > 4 ? c.replace(/\B(?=(\d{3})+(?!\d))/g, NBSP) : c;
  return `${v < 0 && Number(v.toFixed(miejsca)) !== 0 ? '-' : ''}${cale}${u ? `,${u}` : ''}`;
}
export const mld = (v, miejsca = 1) => (v == null ? '-' : `${liczba(v, miejsca)}${NBSP}mld${NBSP}zł`);
export const zl = (v) => (v == null ? '-' : `${liczba(v)}${NBSP}zł`);
export const proc = (v, miejsca = 1, znak = false) => (v == null ? '-' : `${znak && v > 0 ? '+' : ''}${liczba(v, miejsca)}${NBSP}%`);
/** Tekst: twarda spacja po jednoliterowych spójnikach i przyimkach; pauza i półpauza zamienione na łącznik. */
export const tp = (s) => String(s ?? '').replace(/[–—−]/g, '-').replace(/(^|\s)([aiouwzAIOUWZ])\s/g, `$1$2${NBSP}`);

// ---------- wielkości wyprowadzone z pól pliku ----------

/** Wiersz sumy dla roku. */
export const sumaRok = (d, rok) => d.suma.find((s) => s.rok === rok);
/** Wydatki na mieszkańca (pozycja M2) dla roku. */
export const naMieszkanca = (d, rok) => d.na_mieszkanca.find((p) => p.pozycja.startsWith('M2'))?.[String(rok)] ?? null;

/**
 * Skumulowany wzrost cen 2020→2025 odczytany z programów: (1 + wzrost nominalny) / (1 + wzrost realny).
 * Plik nie podaje inflacji rok po roku, więc wykres w cenach stałych dla każdego roku nie jest możliwy.
 * Zwraca medianę ilorazów z programów (różnią się tylko zaokrągleniem) i ich rozrzut do kontroli.
 */
export function wzrostCen(d) {
  const f = d.programy.filter((p) => p.wzrost_nominalny_proc != null && p.wzrost_realny_proc != null)
    .map((p) => (1 + p.wzrost_nominalny_proc / 100) / (1 + p.wzrost_realny_proc / 100)).sort((a, b) => a - b);
  if (!f.length) return null;
  return { czynnik: f[Math.floor(f.length / 2)], rozrzut: f[f.length - 1] - f[0], programow: f.length };
}

/** Programy z kartami świadczeń (identyfikatory kart z eksportu Mapy; brakujące karty są pomijane). */
export const KARTY_PROGRAMOW = {
  'Emerytury i renty FUS (z dodatkami)': ['DU-1998-1118-emerytura', 'DU-1998-1118-renta-z-tytulu-niezdolnosci-do-pracy'],
  'Zasiłki i pozostałe świadczenia FUS': ['DU-1999-636-S001'],
  'Emerytury i renty rolnicze (FER)': ['DU-1991-24-S003'],
  'Emerytury mundurowe (75301)': ['DU-1994-36-S001', 'DU-1994-214-S001'],
  '500+/800+ (85501)': ['SW-wychowawcze'],
  'Świadczenia rodzinne i fundusz alimentacyjny (85502)': ['DU-2003-2255-S01', 'DU-2007-1378-S001'],
  'Świadczenie wspierające (85518)': ['DU-2023-1429-S01'],
  'Aktywny rodzic (85519)': ['DU-2024-858-S001', 'DU-2024-858-S002', 'DU-2024-858-S003'],
  'Pomoc społeczna, dział 852 (BP)': ['DU-2004-593-S01', 'DU-2004-593-S02', 'DU-2004-593-S03'],
  'Emerytury pomostowe (FEP)': ['DU-2008-1656-S001'],
  'Zasiłki dla bezrobotnych i przedemerytalne (FP)': ['DU-2025-620-S003', 'DU-2004-1252-S001'],
};

/** Nazwa programu bez kodu klasyfikacji budżetowej w nawiasie: „800+ (85501)” → „800+”. */
export const nazwaKrotka = (n) => n.replace(/\s*\((?:\d{5}(?:,\s*\d{5})*|BP|FER|FEP|FP)\)\s*$/, '').replace(/^500\+\/800\+/, '800+ (wcześniej 500+)');
/** Kod w nawiasie: „(85501)” → „85501”. */
export const kodProgramu = (n) => /\(([^)]+)\)\s*$/.exec(n)?.[1] ?? null;

/** Przedziały kwantylowe (n klas) dla wartości; zwraca progi górne klas 1..n-1. */
export function kwantyle(wartosci, n = 5) {
  const w = wartosci.filter((v) => v != null).sort((a, b) => a - b);
  return Array.from({ length: n - 1 }, (_, i) => w[Math.floor(((i + 1) * w.length) / n)]);
}
export const mediana = (wartosci) => {
  const w = wartosci.filter((v) => v != null).sort((a, b) => a - b);
  if (!w.length) return null;
  const m = Math.floor(w.length / 2);
  return w.length % 2 ? w[m] : (w[m - 1] + w[m]) / 2;
};

// ---------- mapa powiatów (granice PRG GUGiK, scripts/granice_powiatow.py) ----------

export const SCIEZKA_GRANIC = path.resolve(KATALOG_STRONY, 'data', 'liczby', 'granice_powiatow.json');

/**
 * Ścieżki SVG powiatów i granic województw w układzie viewBox 0 0 szer × wys (całkowite współrzędne).
 * Zwraca null, gdy pliku granic nie ma (wtedy strona pokazuje sam ranking).
 */
export function mapaPowiatow(szer = 1000) {
  if (!existsSync(SCIEZKA_GRANIC)) return null;
  const g = JSON.parse(readFileSync(SCIEZKA_GRANIC, 'utf8'));
  const [W0, H0] = g.meta.rozmiar;
  const s = szer / W0;
  const wys = Math.round(H0 * s);
  const luki = g.luki.map((l) => {
    const pts = []; let x = 0, y = 0;
    for (let i = 0; i < l.length; i += 2) { x += l[i]; y += l[i + 1]; pts.push([Math.round(x * s), Math.round((H0 - y) * s)]); }
    return pts;
  });
  const punkty = (ref) => (ref >= 0 ? luki[ref] : [...luki[~ref]].reverse());
  const uzycie = new Map();
  const powiaty = g.powiaty.map((p) => {
    const czesci = [];
    for (const wiel of p.wielokaty) for (const pierscien of wiel) {
      const pts = [];
      for (const ref of pierscien) {
        const i = ref >= 0 ? ref : ~ref;
        if (!uzycie.has(i)) uzycie.set(i, []);
        uzycie.get(i).push(p.teryt);
        const q = punkty(ref);
        pts.push(...(pts.length ? q.slice(1) : q));
      }
      const uniq = pts.filter((pt, i) => i === 0 || pt[0] !== pts[i - 1][0] || pt[1] !== pts[i - 1][1]);
      if (uniq.length < 3) continue;
      czesci.push(`M${uniq[0][0]} ${uniq[0][1]}` + uniq.slice(1).map((pt, i) => `l${pt[0] - uniq[i][0]} ${pt[1] - uniq[i][1]}`).join('') + 'z');
    }
    return { teryt: p.teryt, d: czesci.join('') };
  });
  // granice województw: łuki zewnętrzne i łuki między powiatami z różnych województw
  const granica = [...uzycie].filter(([, t]) => t.length === 1 || new Set(t.map((x) => x.slice(0, 2))).size > 1)
    .map(([i]) => { const q = luki[i]; return `M${q[0][0]} ${q[0][1]}` + q.slice(1).map((pt, j) => `l${pt[0] - q[j][0]} ${pt[1] - q[j][1]}`).join(''); }).join('');
  return { szer, wys, powiaty, granica, meta: g.meta };
}
