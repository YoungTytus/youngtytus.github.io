// Dane podstrony /liczby/ z data/liczby/liczby.json (eksport projektu Raport_Socjal_Wydatki,
// skrypt Skrypty/eksport_liczby_json.py). Strona nie wpisuje liczb ręcznie: wszystko, co
// pokazuje, jest polem pliku albo prostym działaniem na polach (iloraz, suma, różnica).
import { createHash } from 'node:crypto';
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';

const KATALOG_STRONY = process.env.STRONA_KATALOG ?? process.cwd();
export const SCIEZKA_LICZB = path.resolve(KATALOG_STRONY, 'data', 'liczby', 'liczby.json');
const NBSP = ' ';

let pamiec = null;
/** Dane albo null, gdy pliku nie ma (wtedy strona /liczby/ nie powstaje). */
export function liczby() {
  if (pamiec !== null) return pamiec || null;
  if (!existsSync(SCIEZKA_LICZB)) { pamiec = false; return null; }
  const bajty = readFileSync(SCIEZKA_LICZB);
  const d = JSON.parse(bajty.toString('utf8'));
  const brak = ['meta', 'licznik_2025', 'bez_emerytur_zus_2025', 'suma', 'platnicy_2022_2025_mld', 'programy',
    'na_mieszkanca', 'dzialy_budzetu', 'fundusz_solidarnosciowy', 'wojewodztwa', 'powiaty'].filter((k) => !(k in d));
  if (brak.length) throw new Error(`data/liczby/liczby.json: brak pól ${brak.join(', ')}`);
  d._sha256 = createHash('sha256').update(bajty).digest('hex');
  pamiec = d;
  return d;
}

// ---------- formaty (polskie: twarda spacja tysięcy, przecinek dziesiętny) ----------

export function liczba(v, miejsca = 0) {
  if (v == null || Number.isNaN(v)) return '—';
  const [c, u] = Math.abs(v).toFixed(miejsca).split('.');
  return `${v < 0 ? '−' : ''}${c.replace(/\B(?=(\d{3})+(?!\d))/g, NBSP)}${u ? `,${u}` : ''}`;
}
export const mld = (v, miejsca = 1) => `${liczba(v, miejsca)}${NBSP}mld${NBSP}zł`;
export const zl = (v) => `${liczba(v)}${NBSP}zł`;
export const proc = (v, miejsca = 0, znak = false) => `${znak && v > 0 ? '+' : ''}${liczba(v, miejsca)}${NBSP}%`;

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

/** Udziały w 100 kratkach metodą największych reszt (suma zawsze 100). */
export function kratki(udzialy) {
  const s = udzialy.reduce((a, b) => a + b, 0);
  const surowe = udzialy.map((u) => (u / s) * 100);
  const cale = surowe.map(Math.floor);
  let reszta = 100 - cale.reduce((a, b) => a + b, 0);
  surowe.map((v, i) => [v - cale[i], i]).sort((a, b) => b[0] - a[0]).forEach(([, i]) => { if (reszta > 0) { cale[i]++; reszta--; } });
  return cale;
}

/** Treemap „squarified” (Bruls i in.) w prostokącie W×H; elementy posortowane malejąco. */
export function treemap(elementy, W, H) {
  const suma = elementy.reduce((a, e) => a + e.wartosc, 0);
  const pola = elementy.map((e) => ({ ...e, pole: (e.wartosc / suma) * W * H }));
  const wynik = [];
  let x = 0, y = 0, w = W, h = H, rzad = [];
  const najgorszy = (r, bok) => {
    const s = r.reduce((a, e) => a + e.pole, 0);
    const mx = Math.max(...r.map((e) => e.pole)), mn = Math.min(...r.map((e) => e.pole));
    return Math.max((bok * bok * mx) / (s * s), (s * s) / (bok * bok * mn));
  };
  const uloz = (r) => {
    const s = r.reduce((a, e) => a + e.pole, 0);
    if (w >= h) {
      const sz = s / h; let yy = y;
      r.forEach((e) => { const hh = e.pole / sz; wynik.push({ ...e, x, y: yy, w: sz, h: hh }); yy += hh; });
      x += sz; w -= sz;
    } else {
      const wy = s / w; let xx = x;
      r.forEach((e) => { const ww = e.pole / wy; wynik.push({ ...e, x: xx, y, w: ww, h: wy }); xx += ww; });
      y += wy; h -= wy;
    }
  };
  for (const e of pola) {
    const bok = Math.min(w, h);
    if (!rzad.length || najgorszy([...rzad, e], bok) <= najgorszy(rzad, bok)) rzad.push(e);
    else { uloz(rzad); rzad = [e]; }
  }
  if (rzad.length) uloz(rzad);
  return wynik;
}

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
