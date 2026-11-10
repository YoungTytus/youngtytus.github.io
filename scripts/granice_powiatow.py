"""Granice powiatów do mapy na podstronie /liczby/.

Źródło: PRG (Państwowy Rejestr Granic), GUGiK, usługa WFS AdministrativeBoundaries, warstwa
ms:A02_Granice_powiatow (dane otwarte). Układ EPSG:2180 (metry; pierwsza współrzędna = północna).

Skrypt pobiera warstwę (albo czyta zapisany plik --gml), upraszcza granice z zachowaniem topologii
(wspólny odcinek dwóch powiatów jest upraszczany raz, więc sąsiedzi dalej się stykają) i zapisuje
data/liczby/granice_powiatow.json: łuki kwantowane do pełnych metrów/--krok, kodowane różnicowo,
i dla każdego powiatu listę pierścieni jako indeksów łuków (~i = łuk odwrócony).

Uruchom: py -3.10 scripts/granice_powiatow.py [--gml plik.gml] [--tolerancja 400]
Plik GML nie jest przechowywany; w metadanych zostaje jego SHA-256, adres i data pobrania.
"""
import argparse
import hashlib
import json
import sys
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WYJSCIE = ROOT / 'data' / 'liczby' / 'granice_powiatow.json'
URL = ('https://mapy.geoportal.gov.pl/wss/service/PZGIK/PRG/WFS/AdministrativeBoundaries'
       '?service=WFS&version=2.0.0&request=GetFeature&typeNames=ms:A02_Granice_powiatow&count=1000')
GML = '{http://www.opengis.net/gml/3.2}'
MS = '{http://mapserver.gis.umn.edu/mapserver}'


def wczytaj(sciezka):
    """Lista powiatów: (teryt, nazwa, [wielokąt = [pierścień = [(x, y), ...], ...], ...]); x = wschód, y = północ."""
    wynik = []
    for _, el in ET.iterparse(sciezka, events=('end',)):
        if el.tag != MS + 'A02_Granice_powiatow':
            continue
        teryt = el.findtext(MS + 'JPT_KOD_JE')
        nazwa = el.findtext(MS + 'JPT_NAZWA_')
        wielokaty = []
        for poly in el.iter(GML + 'Polygon'):
            pierscienie = []
            for rodzaj in ('exterior', 'interior'):
                for pl in poly.findall(f'{GML}{rodzaj}/{GML}LinearRing/{GML}posList'):
                    v = [float(t) for t in pl.text.split()]
                    # EPSG:2180 w GML 3.2: kolejność północ, wschód
                    pierscienie.append([(round(v[i + 1]), round(v[i])) for i in range(0, len(v), 2)])
            wielokaty.append(pierscienie)
        wynik.append((teryt, nazwa, wielokaty))
        el.clear()
    return wynik


def oczysc(r):
    out = [p for i, p in enumerate(r) if i == 0 or p != r[i - 1]]
    if len(out) > 1 and out[0] == out[-1]:
        out.pop()
    return out


def douglas_peucker(pts, tol):
    if len(pts) < 3:
        return pts
    zachowaj = [False] * len(pts)
    zachowaj[0] = zachowaj[-1] = True
    stos = [(0, len(pts) - 1)]
    t2 = tol * tol
    while stos:
        a, b = stos.pop()
        (x1, y1), (x2, y2) = pts[a], pts[b]
        dx, dy = x2 - x1, y2 - y1
        d2 = dx * dx + dy * dy
        najw, idx = -1, -1
        for i in range(a + 1, b):
            px, py = pts[i]
            if d2 == 0:
                e = (px - x1) ** 2 + (py - y1) ** 2
            else:
                t = max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / d2))
                e = (px - x1 - t * dx) ** 2 + (py - y1 - t * dy) ** 2
            if e > najw:
                najw, idx = e, i
        if najw > t2:
            zachowaj[idx] = True
            stos += [(a, idx), (idx, b)]
    return [p for p, z in zip(pts, zachowaj) if z]


def topologia(powiaty, tol):
    pierscienie = []  # (indeks powiatu, indeks wielokąta, punkty)
    for pi, (_, _, wiel) in enumerate(powiaty):
        for wi, w in enumerate(wiel):
            for r in w:
                r = oczysc(r)
                if len(r) >= 3:
                    pierscienie.append((pi, wi, r))
    wlasciciele = {}
    for pi, _, r in pierscienie:
        for p in r:
            wlasciciele.setdefault(p, set()).add(pi)
    luki, indeks = [], {}

    def dodaj(pts):
        klucz, odw = tuple(pts), tuple(reversed(pts))
        if klucz in indeks:
            return indeks[klucz]
        if odw in indeks:
            return ~indeks[odw]
        indeks[klucz] = len(luki)
        luki.append(pts)
        return len(luki) - 1

    wynik = [[[] for _ in w] for _, _, w in powiaty]
    for pi, wi, r in pierscienie:
        n = len(r)
        wezly = [i for i in range(n) if wlasciciele[r[i]] != wlasciciele[r[i - 1]] or wlasciciele[r[i]] != wlasciciele[r[(i + 1) % n]]]
        if not wezly:  # pierścień bez węzłów (wyspa, enklawa): wspólny początek w najmniejszym punkcie
            wezly = [min(range(n), key=lambda i: r[i])]
        refs = []
        for k, a in enumerate(wezly):
            b = wezly[(k + 1) % len(wezly)]
            seg = [r[(a + j) % n] for j in range(((b - a) % n or n) + 1)]
            refs.append(dodaj(seg))
        wynik[pi][wi].append(refs)
    proste = []
    for l in luki:
        s = douglas_peucker(l, tol)
        if s[0] == s[-1] and len(s) < 4:  # łuk zamknięty musi zostać trójkątem
            s = [l[0], l[len(l) // 3], l[2 * len(l) // 3], l[0]]
        proste.append(s)
    return proste, wynik


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--gml', help='Zapisany plik GML z WFS (inaczej pobierz).')
    ap.add_argument('--tolerancja', type=float, default=400, help='Tolerancja uproszczenia w metrach.')
    ap.add_argument('--pobrano', help='Data pobrania pliku --gml (RRRR-MM-DD), domyślnie dziś.')
    ap.add_argument('--krok', type=int, default=100, help='Kwantyzacja współrzędnych w metrach.')
    a = ap.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        sciezka = Path(a.gml) if a.gml else Path(tmp) / 'powiaty.gml'
        pobrano = a.pobrano or date.today().isoformat()
        if not a.gml:
            print('Pobieram warstwę powiatów z GUGiK…')
            urllib.request.urlretrieve(URL, sciezka)
        sha = hashlib.sha256(sciezka.read_bytes()).hexdigest()
        powiaty = wczytaj(sciezka)
    if len(powiaty) != 380:
        sys.exit(f'Oczekiwano 380 powiatów, jest {len(powiaty)}.')
    luki, ref = topologia(powiaty, a.tolerancja)
    k = a.krok
    xs = [x for l in luki for x, _ in l]
    ys = [y for l in luki for _, y in l]
    x0, y0 = min(xs) // k, min(ys) // k
    zakod = []
    for l in luki:
        q = [((x // k) - x0, (y // k) - y0) for x, y in l]
        out, px, py = [], 0, 0
        for x, y in q:
            out += [x - px, y - py]
            px, py = x, y
        zakod.append(out)
    dane = {
        'meta': {
            'zrodlo': 'PRG – Państwowy Rejestr Granic, GUGiK (dane otwarte), WFS AdministrativeBoundaries, warstwa A02_Granice_powiatow',
            'url': URL, 'pobrano': pobrano,
            'sha256_gml': sha, 'uklad': 'EPSG:2180, oś y w górę (północ)', 'krok_m': k, 'tolerancja_m': a.tolerancja,
            'przesuniecie': [x0, y0], 'rozmiar': [max(xs) // k - x0, max(ys) // k - y0],
        },
        'luki': zakod,
        'powiaty': [{'teryt': t, 'nazwa': n, 'wielokaty': ref[i]} for i, (t, n, _) in enumerate(powiaty)],
    }
    WYJSCIE.parent.mkdir(parents=True, exist_ok=True)
    WYJSCIE.write_text(json.dumps(dane, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(f'Zapisano {WYJSCIE} ({WYJSCIE.stat().st_size // 1024} KB, {len(luki)} łuków, '
          f'{sum(len(l) for l in luki)} punktów).')


if __name__ == '__main__':
    main()
