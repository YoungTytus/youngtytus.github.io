#!/usr/bin/env python3
"""Z sejfu Socjal (Obsidian + JSON) do statycznej witryny Astro; Python 3.10.4.

Źródła są tylko odczytywane. Nie wyprowadza wartości prawnych z nazwy pliku ani
nie uznaje kandydata automatycznego za potwierdzone świadczenie. Kontrakt bazowy
strona-0.4 + dodatkowy socjal.json dla artykułów i powiązań.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import unicodedata

KONTRAKT = 'strona-0.4'
ELI_RE = re.compile(r'^(DU|MP)/\d{4}/\d+$')
ART_RE = re.compile(r'#arti_([0-9]+[a-z]?)', re.I)
PODSTAWOWE = ('korzysci.json', 'akty.json', 'slowniki.json', 'akty/SHA256SUMS')
TERMINY = {'okres_kwoty', 'termin_wniosku', 'granica_przepisu', 'okres_zasilkowy',
           'harmonogram_dostepnosci', 'termin_wyplaty', 'termin_dokumentu',
           'termin_organu', 'termin_inny', 'wejscie_w_zycie'}


class BladSocjal(Exception):
    pass


def wczytaj(p: Path):
    try:
        return json.loads(p.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as err:
        raise BladSocjal('Nie można odczytać {}: {}'.format(p, err)) from err


def slug(tekst):
    raw = unicodedata.normalize('NFKD', str(tekst)).encode('ascii', 'ignore').decode().lower()
    return re.sub('-+', '-', re.sub('[^a-z0-9]+', '-', raw)).strip('-')


def data_tekstu(wartosc):
    s = str(wartosc or '')[:10]
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', s):
        try:
            datetime.strptime(s, '%Y-%m-%d')
            return s
        except ValueError:
            return None
    return None


def zapis(p: Path, dane):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(dane, ensure_ascii=False, indent=2, sort_keys=False) + '\n', encoding='utf-8')


def sha(p: Path):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def eli_url(eli):
    return 'https://api.sejm.gov.pl/eli/acts/' + eli


def dowod(eli, przepis, cytat, data=None):
    if not ELI_RE.fullmatch(str(eli)):
        raise BladSocjal('Niepoprawny ELI dowodu: {}'.format(eli))
    return {'eli': eli, 'przepis': str(przepis or 'Jednostka nieustalona'),
            'cytat': str(cytat or 'Treść dowodu nie jest dostępna w danych; sprawdź przepis u źródła.'),
            'url': eli_url(eli), 'data_stanu': data_tekstu(data)}


def bez_kwoty():
    return {'rozwiazanie': 'nieustalone', 'regula': None, 'aktualna': None,
            'kwota_ustawowa_zastapiona': None, 'zwiekszenia': [], 'wyliczenie': None,
            'os_czasu': [], 'progi': [], 'trasa': []}


def dowod_rekordu(row, eli, jednostki):
    unit = jednostki.get(row.get('jednostka') or row.get('id_jednostki')) or {}
    ident = str(row.get('jednostka') or row.get('id_jednostki') or '')
    source_eli = row.get('akt') or ident.split('#')[0] or eli
    cytat = row.get('cytat') or unit.get('tekst')
    if not cytat or not ELI_RE.fullmatch(str(source_eli)):
        raise BladSocjal('Brak dowodu strukturalnego: {}'.format(ident or row))
    d = dowod(source_eli, row.get('sciezka') or row.get('przepis') or unit.get('sciezka'),
              cytat, row.get('data_stanu') or (unit.get('dowod') or {}).get('data_stanu'))
    for key in ('sha256', 'strona', 'strony'):
        value = row.get(key) or (unit.get('dowod') or {}).get(key) or unit.get(key)
        if value is not None:
            d['_' + key] = value
    return d


def przenies_terminy(src, k, jednostki):
    for t in src.get('do_kiedy') or []:
        rodzaj = t.get('rodzaj')
        if rodzaj not in TERMINY:
            raise BladSocjal('Nieznany rodzaj terminu: {}'.format(rodzaj))
        row = {'rodzaj': rodzaj, 'data': data_tekstu(t.get('data')),
               'opis': t.get('opis') or t.get('zdanie') or t.get('cytat') or 'Termin z przepisu',
               'skutek': t.get('skutek') or None,
               'dowod': dowod_rekordu(t, k['przepis']['eli'], jednostki)}
        for field in ('od', 'do'):
            if field in t: row[field] = data_tekstu(t[field])
        for field in ('okres', 'zdarzenie', 'przepis'):
            if t.get(field): row[field] = str(t[field])
        k['do_kiedy'].append(row)


def wartosc_rekordu(row):
    tekst = row.get('tekst')
    if not tekst and row.get('wartosc') is not None:
        tekst = '{} zł'.format(row['wartosc'])
    return str(tekst) if tekst else None


def etykieta_wariantu(tekst):
    """Opis wariantu bez wstępu komunikatu („… ogłasza się, że od dnia 1 marca 2026 r.”) i litery wyliczenia."""
    if not tekst:
        return None
    s = ' '.join(str(tekst).split())
    s = re.sub(r'^.*?\bogłasza\s+się,?\s*(?:że\s*)?', '', s, flags=re.I)
    s = re.sub(r'^od\s+dnia\s+\d{1,2}\s+\w+\s+\d{4}\s*r\.\s*', '', s, flags=re.I)
    s = re.sub(r'(\w)-\s+(\w)', r'\1\2', s)
    s = re.sub(r'^(?:[a-z]\)\s*)?', '', s, flags=re.I)
    s = re.sub(r'\bmiesięcznie\s*[–—-]?\s*', '', s, flags=re.I)
    s = ' '.join(s.split()).strip(' ,;:–—-')
    return s or None


PRZYMIOTNIKI_NAGLOWKA = {'najniższ': 'najniższa', 'maksymaln': 'maksymalna', 'minimaln': 'minimalna', 'najwyższ': 'najwyższa'}


def opis_wariantu(row):
    """Etykieta wariantu do wyświetlenia. Z nagłówka punktu komunikatu („kwoty najniższej emerytury i renty”)
    bierzemy tylko dookreślenie („najniższa”), żeby opis był krótki."""
    et = etykieta_wariantu(row.get('wariant'))
    nagl = str(row.get('naglowek_punktu') or '').casefold()
    for rdzen, przymiotnik in PRZYMIOTNIKI_NAGLOWKA.items():
        if et and rdzen in nagl and rdzen not in et.casefold():
            return '{}: {}'.format(przymiotnik, et)
    return et


def etykiety_serii(rows, nazwa):
    """Jeden opis na serię kwot przez wszystkie lata (klucz serii ze skryptu mapy), z najnowszego wpisu.
    Bez tego ta sama seria rozpada się na wykresie na kilka linii, bo stare komunikaty mają inny układ."""
    surowy = lambda r: r.get('wariant_klucz') or etykieta_wariantu(r.get('wariant')) or ''
    # Opis rozlany na następną pozycję (uszkodzony tekst starego PDF: „…całkowicie niezdolnej do pracy,
    # renta dla osoby częściowo …”) to ta sama seria co krótszy klucz, którym się zaczyna.
    klucze = {surowy(r) for r in rows}
    alias = {k: max((x for x in klucze if x and k.startswith(x + ' ')), key=len, default=k) for k in klucze}
    klucz = lambda r: alias[surowy(r)]
    wynik = {}
    for r in sorted(rows, key=lambda r: data_tekstu(r.get('od')) or ''):
        et = opis_wariantu(r) if surowy(r) == klucz(r) else None
        if et or klucz(r) not in wynik:
            wynik[klucz(r)] = et
    if len(wynik) == 1:
        (k, et), = wynik.items()
        rdzenie = [w[:5] for w in nazwa.casefold().split() if len(w) > 3]
        if et and rdzenie and all(x in et.casefold() for x in rdzenie) \
                and not any(p in et.casefold() for p in PRZYMIOTNIKI_NAGLOWKA):
            wynik[k] = None  # „kwota dodatku dopełniającego …” = sama nazwa karty
    return wynik, klucz


def zlote(liczba):
    """'1978.49' -> '1978,49 zł' (bez zaokrąglania poza grosze z danych)."""
    d = Decimal(str(liczba))
    return '{} zł'.format(format(d.quantize(Decimal('0.01')), 'f').replace('.', ','))


def procent(liczba):
    d = Decimal(str(liczba))
    d = d.quantize(Decimal(1)) if d == d.to_integral_value() else d.normalize()
    return '{} %'.format(format(d, 'f').replace('.', ','))


def wczytaj_wielkosci(socjal):
    p = socjal / 'Dane/Mapa/wielkosci.json'
    return (wczytaj(p).get('wielkosci') or {}) if p.is_file() else {}


def wpis_wielkosci(wielkosci, nazwa, od=None, akt=None):
    """Wpis serii wielkości ogłaszanej z cytatem aktu (dowód kwoty bazowej albo limitu)."""
    for w in (wielkosci.get(nazwa) or {}).get('seria') or []:
        if (od is None or w.get('od') == od) and (akt is None or w.get('akt') == akt) \
                and w.get('cytat') and not w.get('konflikt') and ELI_RE.fullmatch(str(w.get('akt'))):
            return w
    return None


def dowod_wielkosci(w):
    d = dowod(w['akt'], 'treść aktu', w['cytat'])
    if w.get('sha256'):
        d['_sha256'] = w['sha256']
    return d


def przenies_obliczona(src, k, jednostki, wielkosci, dzien):
    """Kwota obliczona skryptem mapy (procent wielkości ogłaszanej) -> ile.wyliczenie z dowodem podstawy."""
    s = src.get('ile_podsumowanie') or {}
    ile = k['ile']
    if ile['aktualna'] or ile['wyliczenie']:
        return False
    for o in s.get('obliczona') or []:
        biezacy = next((h for h in o.get('historia') or [] if data_tekstu(h.get('od')) and h['od'] <= dzien
                        and (not h.get('do') or h['do'] >= dzien)), None)
        if not biezacy or not o.get('wielkosc'):
            continue
        baza = wpis_wielkosci(wielkosci, o['wielkosc'], biezacy['od'], biezacy.get('akt'))
        if not baza:
            continue
        nazwa_wielkosci = (wielkosci.get(o['wielkosc']) or {}).get('nazwa') or o['wielkosc']
        ile['wyliczenie'] = {
            'wartosc': zlote(biezacy['wynik']), 'warianty': None, 'od': biezacy['od'],
            'podstawa': {'wartosc': zlote(biezacy['podstawa']), 'od': biezacy['od'], 'zrodlo': baza['akt'],
                         'wielkosc': nazwa_wielkosci, 'dowod': dowod_wielkosci(baza), 'lancuch': None},
            'zaokraglenie': None,
            'uwaga': '{} × {}. {}'.format(procent(o['procent']), nazwa_wielkosci, o.get('uwaga') or ''),
            'flagi': [], 'nieustalone': []}
        if o.get('zaokraglenie'):
            ile['wyliczenie']['nieustalone'].append(nieustalone('zaokraglenie', o['zaokraglenie']))
        ile['regula'] = {'udzial': procent(o['procent']), 'podstawa_id': None, 'opis': o.get('regula') or nazwa_wielkosci}
        ile['rozwiazanie'] = 'regula_procentowa'
        if o.get('jednostka_reguly'):
            ile['trasa'].append({'krok': len(ile['trasa']) + 1,
                                 'opis': '{}: reguła procentowa'.format(o.get('sciezka_reguly') or 'przepis'),
                                 'dowod': dowod_rekordu({'jednostka': o['jednostka_reguly'],
                                                         'sciezka': o.get('sciezka_reguly')}, src['akt'], jednostki)})
        ile['trasa'].append({'krok': len(ile['trasa']) + 1,
                             'opis': '{}: {} od {}'.format(baza['akt'], nazwa_wielkosci, biezacy['od']),
                             'dowod': dowod_wielkosci(baza)})
        return True
    return False


def przenies_limity(src, k, wielkosci):
    """Limity kwoty (np. „nie może być wyższa niż kryterium dochodowe”) z historią wielkości ogłaszanej."""
    if k['ile']['aktualna']:
        return  # kwota aktualna (np. maksymalny zasiłek stały) już pokazuje tę samą wielkość
    for lim in (src.get('ile_podsumowanie') or {}).get('limity') or []:
        if not lim.get('wielkosc') or lim.get('rodzaj') not in ('maksimum', 'minimum'):
            continue
        if '%' in str(lim.get('cytat') or ''):
            continue  # limit to procent wielkości, a seria pokazuje samą wielkość
        seria = [w for w in (wielkosci.get(lim['wielkosc']) or {}).get('seria') or []
                 if w.get('cytat') and w.get('tekst') and not w.get('konflikt')
                 and data_tekstu(w.get('od')) and ELI_RE.fullmatch(str(w.get('akt')))]
        if not seria:
            continue
        seria.sort(key=lambda w: w['od'])
        opis = '{} — {} ({})'.format(lim.get('sciezka') or 'przepis',
                                     'najwyżej' if lim['rodzaj'] == 'maksimum' else 'co najmniej',
                                     lim.get('opis') or lim.get('cytat') or lim['wielkosc'])
        wpisy = []
        for i, w in enumerate(seria):
            wpisy.append({'wartosc': w['tekst'], 'warianty': None, 'od': w['od'], 'do': data_tekstu(w.get('do')),
                          'rodzaj_zmiany': 'pierwszy_znany_wpis' if not i else 'akt_wykonawczy',
                          'poprzednia': seria[i - 1]['tekst'] if i else None, 'roznica': None,
                          'dowod': dowod_wielkosci(w), '_rodzaj': lim['rodzaj'], '_cytat_ustawy': lim.get('cytat')})
        if not any(p['przepis'] == opis for p in k['ile']['progi']):
            k['ile']['progi'].append({'przepis': opis, 'wpisy': wpisy})


def przenies_podsumowanie(src, k, jednostki, dzien):
    s = src.get('ile_podsumowanie') or {}
    ile = k['ile']
    rows = list(s.get('historia') or [])
    for row in s.get('aktualna') or []:
        if row not in rows: rows.append(row)
    rejected = [r for r in rows if r.get('akt') != src['akt'] and (
        'w sprawie wzoru' in str(r.get('tytul_aktu') or '').casefold()
        or src['nazwa'].casefold()[:4] not in str(r.get('cytat') or '').casefold())]
    rejected_ids = {r.get('jednostka') for r in rejected}
    if rejected:
        k['nieustalone'].append(nieustalone('ile.podsumowanie',
            'Odrzucono kwoty zewnętrzne bez bezpośredniego powiązania cytatu ze świadczeniem: ' +
            '; '.join('{}: {}'.format(r.get('akt'), wartosc_rekordu(r)) for r in rejected)))
        k['do_kiedy'] = [t for t in k['do_kiedy'] if not any(
            t['dowod']['eli'] == r.get('akt') and t['dowod']['przepis'] == r.get('sciezka')
            for r in rejected)]
    rows = [r for r in rows if r not in rejected]
    rows.sort(key=lambda row: (data_tekstu(row.get('od')) or '', str(row.get('wariant') or '')))
    # Kwoty z jednego aktu na ten sam okres (np. najniższa emerytura i renta częściowa
    # z jednego komunikatu) to warianty jednego wpisu, a nie nakładające się okresy.
    grupy = {}
    etykiety, klucz_serii = etykiety_serii(rows, src['nazwa'])
    kolejnosc = list(etykiety)
    for row in rows:
        value = wartosc_rekordu(row)
        if not value: continue
        klucz = (row.get('akt'), data_tekstu(row.get('od')), data_tekstu(row.get('do')))
        grupy.setdefault(klucz, []).append((row, value))
    for lista in grupy.values():
        lista.sort(key=lambda rv: kolejnosc.index(klucz_serii(rv[0])))
        row = lista[0][0]
        warianty = []
        for r, value in lista:
            w = {'etykieta': etykiety[klucz_serii(r)], 'wartosc': value}
            if w not in warianty: warianty.append(w)
        jedna = len(warianty) == 1 and not warianty[0]['etykieta']
        poprzednie = []
        for r, _ in lista:
            if r.get('poprzednia') is not None and str(r['poprzednia']) not in poprzednie:
                poprzednie.append(str(r['poprzednia']))
        cytaty = []
        for r, _ in lista:
            if r.get('cytat') and r['cytat'] not in cytaty: cytaty.append(r['cytat'])
        merged = dict(row, cytat=' … '.join(cytaty) or row.get('cytat'))
        rodzaje = [r.get('rodzaj_zmiany') for r, _ in lista]
        ile['os_czasu'].append({'wartosc': warianty[0]['wartosc'] if jedna else None,
            'warianty': None if jedna else warianty,
            'od': data_tekstu(row.get('od')), 'do': data_tekstu(row.get('do')),
            'rodzaj_zmiany': 'akt_wykonawczy' if 'akt_wykonawczy' in rodzaje else (rodzaje[0] or 'pierwszy_znany_wpis'),
            'poprzednia': (poprzednie[0] if len(poprzednie) == 1 else poprzednie) if poprzednie else None,
            'roznica': None, 'dowod': dowod_rekordu(merged, src['akt'], jednostki),
            '_roznica_zrodlowa': row.get('roznica') if len(lista) == 1 else None})
    # Wybór po dacie eksportu, nie po etykiecie „aktualna” źródła.
    current = [w for w in ile['os_czasu'] if w['od'] and w['od'] <= dzien
               and (w['do'] is None or w['do'] >= dzien)]
    if len(current) == 1:
        ile['aktualna'] = {key: current[0][key] for key in ('wartosc', 'warianty', 'od', 'do')}
    elif len(current) > 1:
        k['nieustalone'].append(nieustalone('ile.aktualna', 'Wiele równoległych kwot; nie wybrano jednej stawki.'))
    if ile['os_czasu']:
        ile['rozwiazanie'] = s.get('rozwiazanie') if s.get('rozwiazanie') in (
            'kwota_w_ustawie', 'kwota_z_aktu_wykonawczego', 'odeslanie') else 'nieustalone'
    nominalne = [r for r in s.get('kwota_ustawowa_zastapiona') or []
                 if nominalna_zastepowana(r, jednostki) or any(
                     q.get('jednostka') == r.get('jednostka') and nominalna_zastepowana(q, jednostki)
                     for q in src.get('ile') or [])]
    if nominalne:
        ile['kwota_ustawowa_zastapiona'] = '; '.join(filter(None, (wartosc_rekordu(x) for x in nominalne))) or None
    # Zewnętrzny krok często zawiera tylko identyfikator. Jego cytat jest
    # w rekordzie kwoty; nie zastępujemy go opisem redakcyjnym.
    evidence = {r.get('jednostka'): r for r in rows if r.get('cytat')}
    for step in s.get('trasa') or []:
        if step.get('jednostka') in rejected_ids: continue
        merged = dict(evidence.get(step.get('jednostka')) or {})
        merged.update(step)
        ile['trasa'].append({'krok': len(ile['trasa']) + 1,
            'opis': step.get('opis') or 'Źródło kwoty',
            'dowod': dowod_rekordu(merged, src['akt'], jednostki)})
    for row in nominalne:
        d = dowod_rekordu(row, src['akt'], jednostki)
        if not any(step['dowod'] == d for step in ile['trasa']):
            ile['trasa'].append({'krok': len(ile['trasa']) + 1,
                'opis': 'Nominalna kwota zastępowana lub waloryzowana', 'dowod': d})
    return bool(rows or nominalne or (not rejected and s.get('rozwiazanie') == 'kwota_z_aktu_wykonawczego'))


def nominalna_zastepowana(q, jednostki):
    unit = jednostki.get(q.get('jednostka')) or {}
    przypisy = str(q.get('przypis') or '') + str(unit.get('przypisy') or '')
    return (q.get('rodzaj') == 'kwota_zastepowana_aktem_wykonawczym'
            or any(x.get('kwota_z_aktu_wykonawczego') for x in unit.get('kwoty') or [])
            or bool(re.search(r'aktualn\w* kwot\w* ogłasza|waloryzac', przypisy, re.I)))


def nieustalone(pole, opis):
    return {'pole': pole, 'powod': opis}


# Ręczne analizy ustaw (paczki ChatGPT) w sejfie Socjal. Format kart wspólny: id, nazwa, rodzaj, komu,
# regula_kwoty, warunki, wykluczenia, zrodla. Różnice: źródło (`id_jednostki` w FUS, `akt` w SW) i pole
# kwoty w historii (`wartosc` w FUS, `kwota` w SW). `kwoty`: karta → parametr historii z kwotą karty.
# `aliasy`: nazwa kandydata automatycznego → id karty ręcznej tej samej ustawy (bez dublowania kart).
PACZKI_RECZNE = (
    {'prefiks': 'FUS', 'akt': 'DU/1998/1118', 'wymagana': True,
     'karty': 'Dane/FUS/karty.json', 'historia': 'Dane/FUS/history_all_verified.json', 'zmiana': 'waloryzacja',
     'kwoty': {'zasilek_pogrzebowy': 'zasilek_pogrzebowy_limit', 'dodatek_pielegnacyjny': 'dodatek_pielegnacyjny',
               'dodatek_sierota_zupelna': 'dodatek_sierota_zupelna'},
     'aliasy': {}, 'pomin': {}},
    {'prefiks': 'SW', 'akt': 'DU/2016/195', 'wymagana': False,
     'karty': 'Dane/SW/core_cards.json', 'historia': 'Dane/SW/history_verified.json', 'zmiana': 'nowelizacja',
     'kwoty': {'wychowawcze': 'swiadczenie_wychowawcze_kwota_pelna',
               'naprzemienna': 'kwota_na_rodzica_opieka_naprzemienna'},
     'aliasy': {'świadczenie wychowawcze': 'wychowawcze'},
     # kandydaci automatyczni bez odpowiednika w pełnej ręcznej analizie ustawy (szum słownika)
     'pomin': {'opieka': 'art. 22 dotyczy zbiegu praw rodziców i opiekunów, nie odrębnego świadczenia; '
                         'art. 1 ust. 2b — warunek aktywności zawodowej cudzoziemców'}},
)


def zrodlo_reczne(z, akt):
    ident = z.get('id_jednostki') or ''
    eli = ident.split('#')[0] if '#' in ident else (z.get('akt') or z.get('eli') or akt)
    d = dowod(eli, z.get('przepis'), z.get('cytat'), z.get('stan_pdf') or z.get('data_stanu'))
    for key in ('sha256', 'strona'):
        if z.get(key) is not None:
            d['_' + key] = z[key]
    return d


def historie_reczne(root, paczki=PACZKI_RECZNE):
    parametry = defaultdict(list)
    for paczka in paczki:
        sciezka = root / paczka['historia']
        for p in (wczytaj(sciezka) if sciezka.is_file() else []):
            if not p.get('parametr') or not data_tekstu(p.get('od')):
                continue
            src = p.get('source') or {}
            eli = src.get('eli') or src.get('akt') or ''
            if not ELI_RE.fullmatch(str(eli)):
                continue
            typ = p.get('typ') or p.get('status_wartosci')
            parametry[p['parametr']].append({
                'parametr': p['parametr'], 'od': data_tekstu(p['od']), 'do': data_tekstu(p.get('do')),
                'wartosc': p.get('wartosc') if p.get('wartosc') is not None else p.get('kwota'),
                'jednostka': p.get('jednostka'), 'typ': typ,
                'dowod': dict(dowod(eli, src.get('przepis'), src.get('cytat')),
                              **({'_sha256': src['sha256']} if src.get('sha256') else {})),
                'wyliczona': str(typ or '').startswith(('kwota_obliczona', 'obliczenie')),
                'status': p.get('status') or p.get('status_wartosci'), 'paczka': paczka['prefiks'],
                'zmiana': paczka['zmiana'],
            })
    for p in parametry.values():
        p.sort(key=lambda v: (v['od'], v['typ'] or ''))
    return dict(sorted(parametry.items()))


def kwota_z_historii(b, hist, param, dzien):
    rekordy = hist.get(param, [])
    for h in rekordy:
        try:
            kwota = zlote(h['wartosc'])
        except (InvalidOperation, ValueError, TypeError):
            continue
        poprzednia = b['ile']['os_czasu'][-1]['wartosc'] if b['ile']['os_czasu'] else None
        wpis = {'wartosc': kwota, 'warianty': None, 'od': h['od'], 'do': h['do'],
                'rodzaj_zmiany': 'pierwszy_znany_wpis' if not b['ile']['os_czasu'] else h.get('zmiana', 'waloryzacja'),
                'poprzednia': poprzednia, 'roznica': None, 'dowod': h['dowod']}
        b['ile']['os_czasu'].append(wpis)
    if b['ile']['os_czasu']:
        wyliczona = any(h['wyliczona'] for h in rekordy)
        # kwota wyliczona z reguły karty (np. połowa przy opiece naprzemiennej) = formuła, nie cytat kwoty
        b['ile']['rozwiazanie'] = ('kwota_w_ustawie' if not wyliczona
                                   else 'formula' if b['ile']['regula'] else 'nieustalone')
        current = [w for w in b['ile']['os_czasu'] if w['od'] <= dzien and (w['do'] is None or w['do'] >= dzien)]
        # Nie wyciągamy aktualnej kwoty z kilku nakładających się wersji.
        if len(current) == 1:
            x = current[0]
            b['ile']['aktualna'] = {'wartosc': x['wartosc'], 'warianty': None, 'od': x['od'], 'do': x['do']}
        elif len(current) > 1:
            b['nieustalone'].append(nieustalone('ile.aktualna', 'Znaleziono nakładające się okresy historii, wymagany przegląd.'))


def rodzaj_reczny(k):
    nazwa = slug(k.get('rodzaj') or '').replace('-', '_')   # „wygaśniecie_…” → „wygasniecie_…”
    if 'jednorazowe' in nazwa:
        return 'swiadczenie_jednorazowe'
    if k['id'] in ('c_zwolnienie_oplat', 'c_bezplatne_poswiadczenia') or 'zwolnienie' in nazwa:
        return 'zwolnienie'
    if 'transfer_instytucjonalny' in nazwa:
        return 'dofinansowanie'     # koszty obsługi organu (SW): środki dla instytucji, nie dla rodzica
    if nazwa in ('mechanizm_podwyzszenia', 'mechanizm_zbiegu', 'zwiekszenie_swiadczenia') or k['id'].startswith('c_') \
            or nazwa.startswith(('ochrona', 'ulga', 'wygas', 'usluga', 'forma', 'historyczna_odnoga')):
        return 'uprawnienie'
    return 'swiadczenie_okresowe'


def przepis_art_id(eli, unit):
    found = ART_RE.search(str(unit))
    return '{}-art-{}'.format(eli.replace('/', '-'), found.group(1).lstrip('0') or '0') if found else None



def wczytaj_karty_md(root):
    """Zapisane notatki Obsidiana są równorzędnym źródłem opisu redakcyjnego.

    Nie interpretujemy samodzielnie liczb z tekstu prozatorskiego jako kwot
    aktualnych. Takie kwoty muszą pozostać w danych strukturalnych z dowodami.
    """
    cards = {}
    for p in sorted((root / 'Swiadczenia').glob('**/*.md')):
        t = p.read_text(encoding='utf-8-sig')
        if not t.startswith('---'):
            continue
        fm = re.match(r'\A---\s*\n(.*?)\n---\s*\n', t, re.S)
        if not fm:
            continue
        meta = {}
        for line in fm.group(1).splitlines():
            key, sep, value = line.partition(':')
            if sep and re.fullmatch(r'[a-z_]+', key.strip()):
                meta[key.strip()] = value.strip().strip('"\'')
        if meta.get('typ') != 'karta_korzysci':
            continue
        ident = meta.get('identyfikator')
        if not ident or ident in cards:
            if ident in cards:
                raise BladSocjal('Dwie notatki świadczenia o identyfikatorze {}.'.format(ident))
            continue
        mtitle = re.search(r'^# (.+)$', t, re.M)
        heading = mtitle.group(1).strip() if mtitle else p.stem
        sections = {}
        for match in re.finditer(r'(?m)^## (.+)\s*$', t):
            end = re.search(r'(?m)^## ', t[match.end():])
            content = t[match.end():match.end()+end.start() if end else len(t)].strip()
            sections[match.group(1).strip().lower()] = content
        cards[ident] = {'meta': meta, 'tytul': heading, 'sekcje': sections,
                        'plik': p.relative_to(root).as_posix()}
    return cards


def uzupelnij_notatkami(socjal, benefits, extras, na_dzien):
    notes = wczytaj_karty_md(socjal)
    assigned = set()
    for k in benefits:
        src = extras[k['id']]['zrodlo_id']
        n = notes.get(src)
        if not n:
            continue
        assigned.add(src)
        parts = n['sekcje']
        extras[k['id']]['plik_notatki'] = n['plik']
        if extras[k['id']]['pochodzenie'].startswith('reczna_'):
            if parts.get('komu przysługuje'):
                k['komu'] = parts['komu przysługuje']
            extras[k['id']]['opis_kwoty_z_notatki'] = parts.get('ile wynosi')
        else:
            # Nie nadpisujemy maszynowych dowodów parafrazami wygenerowanymi
            # przez ten sam skrypt źródłowy.
            extras[k['id']]['opis_kwoty_z_notatki'] = None
    # Ręcznie dodana karta w Obsidianie pojawi się na stronie, nawet jeśli
    # nie została jeszcze zsynchronizowana do JSON. Nie udajemy przy tym,
    # że nieobecny w notatce dowód/kwota został zweryfikowany.
    for ident, n in notes.items():
        if ident in assigned or n['meta'].get('generator'):
            continue
        eli = n['meta'].get('ustawa') or n['meta'].get('akt')
        if not ELI_RE.fullmatch(str(eli)):
            continue
        bid = 'SOCJAL-' + slug(ident)
        if any(b['id'] == bid for b in benefits):
            raise BladSocjal('Powtórzony identyfikator nowej notatki: ' + bid)
        sections = n['sekcje']
        k = {'id': bid, 'slug': bid.lower(), 'nazwa': n['tytul'],
             'rodzaj_korzysci': 'uprawnienie', 'status': 'do_ustalenia',
             'komu': sections.get('komu przysługuje', ''), 'opis_prosty': None,
             'sytuacje': [], 'sytuacje_zrodlo': None,
             'przepis': dowod(eli, 'Podstawa do ustalenia', 'Brak jednoznacznego cytatu w danych ustrukturyzowanych.'),
             'ile': bez_kwoty(), 'do_kiedy': [], 'powiazane': [],
             'stan': {'data_stanu': data_tekstu(n['meta'].get('stan_tekstu')) or na_dzien,
                      'tekst': 'tekst ujednolicony (informacyjny)'},
             'nieustalone': [nieustalone('przepis', 'Nowa karta istnieje tylko w notatce; wymaga dowodu w JSON.'),
                            nieustalone('ile', 'Nie ma jeszcze zweryfikowanej kwoty strukturalnej.')],
             'flagi': ['Nowa karta z notatki Obsidiana: niezweryfikowana.']}
        benefits.append(k)
        extras[bid] = {'pochodzenie': 'notatka', 'zrodlo_id': ident,
                       'rodzaj_zrodlowy': n['meta'].get('charakter'),
                       'status_zrodlowy': n['meta'].get('status'),
                       'artykuly': [], 'jednostki': [], 'historia_parametr': None,
                       'plik_notatki': n['plik'],
                       'opis_kwoty_z_notatki': sections.get('ile wynosi')}


def art_z_przepisu(eli, przepis):
    found = re.match(r'\s*art\.\s*(\d+[a-z]?)', str(przepis or ''), re.I)
    return '{}-art-{}'.format(eli.replace('/', '-'), found.group(1)) if found else None


def karty_paczki(socjal, paczka, historia, jednostki, na_dzien, benefits, extra_karty, aliasy):
    """Karty ręcznej analizy jednej ustawy (FUS, SW): opis, formuła, terminy, trasa źródeł i kwota z historii."""
    prefiks, akt = paczka['prefiks'], paczka['akt']
    po_id = {}
    for karta in wczytaj(socjal / paczka['karty']):
        if not karta.get('id') or not karta.get('zrodla'):
            raise BladSocjal('Karta {} bez id albo źródeł.'.format(prefiks))
        bid = prefiks + '-' + slug(karta['id'])
        proven = zrodlo_reczne(karta['zrodla'][0], akt)
        rodzaj = (karta.get('rodzaj') or '').lower()
        k = {'id': bid, 'slug': bid.lower(), 'nazwa': karta['nazwa'],
             'rodzaj_korzysci': rodzaj_reczny(karta),
             # „historyczne_*” w paczce SW: świadczenie albo dodatek zastąpiony ustawowo
             'status': 'zamknieta' if rodzaj.startswith('historyczn') else 'do_ustalenia',
             'komu': karta.get('komu') or 'Krąg uprawnionych nieustalony w karcie.',
             'opis_prosty': None, 'sytuacje': [], 'sytuacje_zrodlo': None,
             'przepis': proven, 'ile': bez_kwoty(), 'do_kiedy': [], 'powiazane': [],
             'stan': {'data_stanu': proven['data_stanu'] or na_dzien, 'tekst': 'tekst ujednolicony (informacyjny)'},
             'nieustalone': [], 'flagi': ['Opracowanie ręczne; historia uprawnień może być niepełna.']}
        for typ, key in [('warunek', 'warunki'), ('wykluczenie', 'wykluczenia')]:
            for txt in karta.get(key) or []:
                if txt: k['powiazane'].append({'typ': typ, 'cytat': str(txt)})
        # Zachowujemy opis formuły bez obliczania indywidualnego świadczenia.
        formula = karta.get('regula_kwoty')
        if formula:
            k['ile']['rozwiazanie'] = 'formula'
            k['ile']['regula'] = {'udzial': None, 'podstawa_id': None, 'opis': formula}
        else:
            k['nieustalone'].append(nieustalone('ile.regula_kwoty', 'Brak formuły kwoty.'))
        przenies_terminy(karta, k, jednostki)
        k['ile']['trasa'] = [{'krok': i + 1, 'opis': 'Źródło karty: {}'.format(z.get('przepis') or 'jednostka'),
                              'dowod': zrodlo_reczne(z, akt)}
                             for i, z in enumerate(z for z in karta['zrodla'] if z.get('cytat'))]
        przypisanie = paczka['kwoty'].get(karta['id'])
        if przypisanie:
            kwota_z_historii(k, historia, przypisanie, na_dzien)
            # Zmienność przepisów ma pierwszeństwo nad niezależnym domniemaniem bieżącego prawa.
            if k['ile']['aktualna']:
                k['nieustalone'] = [u for u in k['nieustalone'] if u['pole'] != 'ile.regula_kwoty']
        benefits.append(k)
        po_id[karta['id']] = k
        jednostki_karty = [z.get('id_jednostki') for z in karta['zrodla'] if z.get('id_jednostki')]
        article_refs = sorted(({przepis_art_id(x.split('#')[0], x) for x in jednostki_karty}
                               | {art_z_przepisu(z.get('akt') or akt, z.get('przepis'))
                                  for z in karta['zrodla'] if not z.get('id_jednostki')}) - {None})
        extra_karty[bid] = {'pochodzenie': 'reczna_' + prefiks, 'zrodlo_id': karta['id'],
                            'rodzaj_zrodlowy': karta.get('rodzaj'), 'status_zrodlowy': karta.get('status'),
                            'artykuly': article_refs, 'jednostki': jednostki_karty,
                            'historia_parametr': przypisanie,
                            # SW: „czas” to opis; FUS: „czas” bywa strukturą (okna, warunki) i zostaje w danych źródłowych
                            'uwaga_czasowa': karta.get('uwaga_czasowa') or (karta['czas'] if isinstance(karta.get('czas'), str) else None),
                            'odsylacze_do_sprawdzenia': karta.get('odeslania_do_sprawdzenia')}
    for nazwa, ident in paczka['aliasy'].items():
        if ident in po_id:
            aliasy[(akt, nazwa)] = po_id[ident]


def dowod_wyliczenia(d):
    out = dowod(d['akt'], d.get('przepis'), d.get('cytat'))
    if d.get('sha256'):
        out['_sha256'] = d['sha256']
    return out


def przenies_wyliczenia(socjal, benefits, wielkosci, dzien):
    """Karty bez kwoty: mechanizmy kwot ze skryptu mapy (Dane/Mapa/wyliczenia_kwot.json, polecenie
    `python Skrypty/mapa.py wyliczenia`). Kwota → aktualna; minimum/maksimum → limit z historią wielkości;
    przykład → wyliczenie pomocnicze z krokami; kwota indywidualna → wyjaśnienie w „Nie ustalono”."""
    p = socjal / 'Dane/Mapa/wyliczenia_kwot.json'
    karty = wczytaj(p).get('karty', {}) if p.is_file() else {}
    for k in benefits:
        wyniki = (karty.get(k['id']) or {}).get('wyniki') or []
        ile = k['ile']
        if not wyniki or ile['aktualna'] or ile['wyliczenie']:
            continue
        kwoty = [r for r in wyniki if r['rodzaj'] == 'kwota']
        if kwoty:
            warianty = [{'etykieta': r.get('wariant'), 'wartosc': r['tekst']} for r in kwoty]
            jedna = len(warianty) == 1 and not warianty[0]['etykieta']
            od = kwoty[0].get('od')
            ile['aktualna'] = {'wartosc': warianty[0]['wartosc'] if jedna else None, 'warianty': None if jedna else warianty,
                               'od': od, 'do': None, '_mechanizm': kwoty[0]['mechanizm'], '_kroki': kwoty[0]['kroki']}
            ile['os_czasu'].append({'wartosc': ile['aktualna']['wartosc'], 'warianty': ile['aktualna']['warianty'], 'od': od, 'do': None,
                                    'rodzaj_zmiany': 'pierwszy_znany_wpis', 'poprzednia': None, 'roznica': None,
                                    'dowod': dowod_wyliczenia(kwoty[0]['dowody'][0])})
            # sposób ustalenia według mechanizmu: kwota ogłaszana, kwota w ustawie, procent/połowa innej kwoty, odesłanie
            mech = kwoty[0]['mechanizm']
            if kwoty[0].get('wielkosc'):
                ile['rozwiazanie'] = 'kwota_z_aktu_wykonawczego'
            elif mech in ('procent_kwoty_swiadczenia', 'polowa_kwoty'):
                ile['rozwiazanie'] = 'regula_procentowa'
                ile['regula'] = {'udzial': '50 %' if mech == 'polowa_kwoty' else (kwoty[0].get('wariant') or '').split(' ')[0] + ' %',
                                 'podstawa_id': None, 'opis': kwoty[0]['kroki'][0][:400]}
            elif mech in ('odeslanie_wysokosci', 'odeslanie_kwoty_artykulu', 'kwota_karty_glownej'):
                ile['rozwiazanie'] = 'odeslanie'
            else:
                ile['rozwiazanie'] = 'kwota_w_ustawie'
            for r in kwoty:
                ile['trasa'].append({'krok': len(ile['trasa']) + 1, 'opis': '; '.join(r['kroki'])[:600],
                                     'dowod': dowod_wyliczenia(r['dowody'][0])})
            lata = [int(x) for x in re.findall(r'\b(19\d\d|20\d\d)\b', kwoty[0].get('okres_tekst') or '')]
            if lata and max(lata) < int(dzien[:4]):
                k['status'] = 'zamknieta'      # jednorazowa wypłata z przeszłości (np. art. 194b: marzec 2005 i 2006)
        for r in wyniki:
            if r['rodzaj'] not in ('minimum', 'maksimum'):
                continue
            opis = '{} — {} ({})'.format(r['dowody'][0]['przepis'], 'najwyżej' if r['rodzaj'] == 'maksimum' else 'co najmniej',
                                        r.get('wariant') or (wielkosci.get(r.get('wielkosc') or '') or {}).get('nazwa') or 'kwota w ustawie')
            if any(x['przepis'] == opis or (x['wpisy'] and x['wpisy'][-1].get('_rodzaj') == r['rodzaj']
                                             and x['wpisy'][-1]['wartosc'].replace(',00', '') == r['tekst'].replace(',00', ''))
                   for x in ile['progi']):
                continue        # ten sam limit już z danych limitów skryptu mapy
            seria = [w for w in (wielkosci.get(r.get('wielkosc') or '') or {}).get('seria') or []
                     if w.get('cytat') and w.get('tekst') and not w.get('konflikt') and data_tekstu(w.get('od'))]
            seria.sort(key=lambda w: w['od'])
            krot = Decimal(str(r.get('krotnosc') or 1))
            wpisy = []
            for i, w in enumerate(seria):
                tekst = w['tekst'] if krot == 1 else zlote(Decimal(str(w['wartosc'])) * krot)
                wpisy.append({'wartosc': tekst, 'warianty': None, 'od': w['od'], 'do': data_tekstu(w.get('do')),
                              'rodzaj_zmiany': 'pierwszy_znany_wpis' if not i else 'akt_wykonawczy',
                              'poprzednia': wpisy[-1]['wartosc'] if wpisy else None, 'roznica': None,
                              'dowod': dowod_wielkosci(w), '_rodzaj': r['rodzaj'], '_kroki': r['kroki']})
            if not wpisy:
                wpisy = [{'wartosc': r['tekst'], 'warianty': None, 'od': r.get('od') or k['stan']['data_stanu'], 'do': None,
                          'rodzaj_zmiany': 'pierwszy_znany_wpis', 'poprzednia': None, 'roznica': None,
                          'dowod': dowod_wyliczenia(r['dowody'][0]), '_rodzaj': r['rodzaj'], '_kroki': r['kroki']}]
            ile['progi'].append({'przepis': opis, 'wpisy': wpisy})
        przyklady = [r for r in wyniki if r['rodzaj'] == 'przyklad']
        if przyklady and not ile['aktualna']:
            r0 = przyklady[0]
            baza = next((d for d in r0['dowody'] if d.get('przepis') == 'treść aktu'), None)
            w0 = wielkosci.get(r0.get('wielkosc') or '') or {}
            ile['wyliczenie'] = {
                'wartosc': r0['tekst'] if len(przyklady) == 1 else None,
                'warianty': None if len(przyklady) == 1 else [
                    {'etykieta': r.get('wariant') or r['mechanizm'], 'udzial': r.get('udzial_procent') or 'przykład', 'wartosc': r['tekst']}
                    for r in przyklady],
                'od': r0.get('od'),
                'podstawa': {'wartosc': None, 'od': r0.get('od'), 'zrodlo': baza['akt'], 'wielkosc': w0.get('nazwa'),
                             'dowod': dowod_wyliczenia(baza), 'lancuch': None} if baza else None,
                'zaokraglenie': None,
                'uwaga': 'Przykład: wynik zależy od danych osoby (dochód, liczba dni, wysokość innego świadczenia). '
                         + ' | '.join('; '.join(r['kroki']) for r in przyklady)[:1500],
                'flagi': [], 'nieustalone': [], '_kroki': [x for r in przyklady for x in r['kroki']]}
            if ile['rozwiazanie'] == 'nieustalone':
                ile['rozwiazanie'] = 'formula'
                if not ile['regula']:
                    ile['regula'] = {'udzial': None, 'podstawa_id': None, 'opis': przyklady[0]['kroki'][0][:400]}
        for r in wyniki:
            if r['rodzaj'] == 'indywidualna' and not ile['aktualna']:
                k['nieustalone'].append(nieustalone('ile.kwota_indywidualna', r.get('wyjasnienie') or ('Kwota indywidualna: ' + '; '.join(r['kroki'])[:400])))
                break


def zastosuj_standard(socjal, benefits):
    """Ujednolicone nazwy, opisy i „komu” (Dane/Mapa/standard_kart.json, kontrola: `python Skrypty/mapa.py standard`).
    Cytat przepisu zostaje w polu `przepis`, pierwotne „komu” w `_komu_zrodlowe`."""
    p = socjal / 'Dane/Mapa/standard_kart.json'
    standard = wczytaj(p).get('karty', {}) if p.is_file() else {}
    for k in benefits:
        s = standard.get(k['id'])
        if not s:
            continue
        k['_nazwa_zrodlowa'], k['_komu_zrodlowe'] = k['nazwa'], k['komu']
        k['nazwa'] = s.get('nazwa') or k['nazwa']
        k['opis_prosty'] = s.get('opis') or k['opis_prosty']
        k['komu'] = s.get('komu') or k['komu']
        if s.get('forma') in ('pieniezne', 'niepieniezne'):
            k['forma'] = s['forma']
        # rodzaj zgodny z formą: wypłata 50 % renty socjalnej nie jest „świadczeniem rzeczowym”
        if k.get('forma') == 'pieniezne' and k['rodzaj_korzysci'] == 'swiadczenie_rzeczowe':
            k['rodzaj_korzysci'] = 'swiadczenie_okresowe'
        elif k.get('forma') == 'niepieniezne' and k['rodzaj_korzysci'] in ('swiadczenie_okresowe', 'swiadczenie_jednorazowe'):
            k['rodzaj_korzysci'] = 'swiadczenie_rzeczowe'
        if s.get('rodzaj'):
            k['rodzaj_korzysci'] = s['rodzaj']


def forma_karty(k, rodzaj_zrodlowy, reguly):
    """Pieniężne / niepieniężne (rzecz, usługa, miejsce). Karta z kwotą jest pieniężna."""
    if k['ile']['aktualna'] or k['ile']['wyliczenie'] or k['ile']['os_czasu']:
        return 'pieniezne'
    f = reguly.get('forma') or {}
    nazwa = k['nazwa'].casefold()
    if k['rodzaj_korzysci'] == 'swiadczenie_rzeczowe':
        return 'niepieniezne'
    # rdzenie z reguł; najpierw pieniężne („świadczenie dla opiekuna” nie jest usługą opieki)
    if any(h in nazwa for h in f.get('hasla_pieniezne', [])):
        return 'pieniezne'
    if any(h in nazwa for h in f.get('hasla_niepieniezne', [])):
        return 'niepieniezne'
    if k['rodzaj_korzysci'] in ('swiadczenie_okresowe', 'swiadczenie_jednorazowe', 'dofinansowanie'):
        return 'pieniezne'
    return 'nieustalona'


def kwalifikuj_do_mapy(socjal, benefits, extra_karty):
    """Mapa socjalu = to, co państwo daje osobie albo rodzinie. Kolejność: decyzja właściciela
    (Dane/Mapa/kwalifikacja/decyzje_wlasciciela.json), potem reguły (Dane/Slowniki/kwalifikacja_socjalu.json):
    dla kandydata automatycznego wynik skryptu mapy, dla karty ręcznej rodzaj i prefiks identyfikatora.
    Pozycje poza mapą nie trafiają na stronę; zostają w socjal.json z powodem."""
    p_reg, p_dec = socjal / 'Dane/Slowniki/kwalifikacja_socjalu.json', socjal / 'Dane/Mapa/kwalifikacja/decyzje_wlasciciela.json'
    reguly = wczytaj(p_reg) if p_reg.is_file() else {}
    dec = wczytaj(p_dec) if p_dec.is_file() else {}
    decyzje = {d['id']: d for d in dec.get('decyzje', [])}
    opisy = dict(dec.get('powody') or {})
    rr = reguly.get('reguly_kart_recznych') or {}
    zostaja, poza = [], []
    for k in benefits:
        meta = extra_karty[k['id']]
        forma_skryptu = (meta.get('kwalifikacja_automatu') or {}).get('forma')
        # skrypt mapy zna treść przepisu („w postaci jednego gorącego posiłku”); bez kwoty jego forma ma pierwszeństwo
        k['forma'] = forma_skryptu if forma_skryptu == 'niepieniezne' and not k['ile']['aktualna'] \
            else forma_karty(k, meta.get('rodzaj_zrodlowy'), reguly)
        d = decyzje.get(k['id'])
        powod, zrodlo, uwaga = None, None, None
        if d:
            if d['stosowanie'] == 'usun':
                powod, zrodlo, uwaga = d['powod'], 'decyzja_wlasciciela', d.get('uwaga')
            elif d['stosowanie'] == 'wstrzymane':
                k['flagi'].append('Właściciel wskazał usunięcie, ale nie ustalono powodu — do potwierdzenia.')
            if d.get('sygnal'):
                meta['sygnal_kwalifikacji'] = d['sygnal']
        elif meta['pochodzenie'] == 'automat':
            kw = meta.get('kwalifikacja_automatu') or {}
            if kw.get('socjal') is False:
                powod, zrodlo, uwaga = kw.get('powod'), 'regula_skryptu_mapy', kw.get('regula')
        elif meta['pochodzenie'].startswith('reczna_'):
            rodzaj = slug(meta.get('rodzaj_zrodlowy') or '').replace('-', '_')
            ident = meta.get('zrodlo_id') or ''
            powod = next((v for p, v in (rr.get('rodzaj_prefiks') or {}).items() if rodzaj.startswith(p)), None) \
                or next((v for p, v in (rr.get('id_prefiks') or {}).items() if ident.startswith(p)), None)
            zrodlo = 'regula_kart_recznych' if powod else None
        if powod:
            poza.append({'id': k['id'], 'nazwa': k['nazwa'], 'powod': powod, 'opis_powodu': opisy.get(powod),
                         'zrodlo_decyzji': zrodlo, 'uwaga': uwaga, 'forma': k['forma'],
                         'pochodzenie': meta['pochodzenie']})
            del extra_karty[k['id']]
        else:
            zostaja.append(k)
    return zostaja, poza


def pliki_aktow(socjal):
    """Odnośniki do PDF w API Sejmu (bez kopiowania plików): tekst ujednolicony ustawy z przebiegu skryptu mapy
    (Dane/Mapa/<kod>/przebieg.json) i teksty aktów wykonawczych (Dane/Mapa/<kod>/powiazane/*.json) — adres, SHA-256,
    rozmiar i data pobrania zapisane przy odczycie."""
    wynik = defaultdict(dict)
    def dodaj(eli, z, data_stanu=None):
        url, typ = z.get('url'), z.get('typ') or z.get('typ_tekstu')
        if not (ELI_RE.fullmatch(str(eli)) and url and re.match(r'^https://api\.sejm\.gov\.pl/eli/acts/', url)
                and typ in ('U', 'O') and re.fullmatch(r'[0-9a-f]{64}', str(z.get('sha256'))) and z.get('rozmiar')):
            return
        nazwa = re.sub(r'[^A-Za-z0-9_.-]', '_', z.get('nazwa_api') or url.rsplit('/', 1)[-1])
        kod = eli.replace('/', '-')
        wynik[eli][typ] = {'rodzaj': typ, 'plik': 'akty/{}/{}'.format(kod, nazwa),
                           'nazwa_pobierania': '{}_{}.pdf'.format(kod, 'tekst-ujednolicony' if typ == 'U' else 'tekst-ogloszony'),
                           'sha256': z['sha256'], 'rozmiar': int(z['rozmiar']), 'url_zrodla': url,
                           'pobrano': z.get('pobrano'), 'data_stanu': data_tekstu(data_stanu or z.get('data_stanu')),
                           'eli_obwieszczenia': None, 'uzyty_w_danych': True, 'zrodlo': 'API Sejmu (ELI)'}
    for kat in sorted((socjal / 'Dane/Mapa').glob('DU-*')):
        pr = kat / 'przebieg.json'
        if pr.is_file():
            meta = wczytaj(pr)
            dodaj(meta.get('akt'), meta.get('zrodlo') or {})
        for pw in sorted((kat / 'powiazane').glob('*.json')) if (kat / 'powiazane').is_dir() else []:
            try:
                z = json.loads(pw.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue
            dodaj(z.get('akt'), z.get('zrodlo') or {})
    # rejestry źródeł ręcznych analiz (FUS, SW): akty cytowane w kartach i historii kwot (dawne komunikaty, nowelizacje)
    for paczka in PACZKI_RECZNE:
        rej = socjal / str(Path(paczka['karty']).parent) / 'zrodla_manifest.json'
        for e in (wczytaj(rej) if rej.is_file() else []):
            for f in e.get('pliki') or []:
                typ = f.get('typ')
                if typ in wynik.get(e.get('eli'), {}):
                    continue
                dodaj(e.get('eli'), {'url': f.get('url'), 'typ': typ, 'sha256': f.get('sha256'), 'rozmiar': f.get('bajtow') or f.get('rozmiar'),
                                     'pobrano': f.get('pobrano'), 'nazwa_api': (f.get('url') or '').rsplit('/', 1)[-1]},
                      f.get('data_stanu'))
    return {eli: list(d.values()) for eli, d in wynik.items()}


# ---------------------------------------------------------------- Analizy ELI (analizy ustaw przez AI z kolejki)
# Publikujemy tylko analizy zamknięte kontrolą (`dane/stan.json`: status). Pozostałe zostają w sejfie.
STATUSY_ANALIZ_ELI = ('sprawdzona_w_zakresie',)
TERMINY_ANALIZ = {'okres_przyznania': 'okres_zasilkowy', 'okres_zasilkowy': 'okres_zasilkowy', 'termin_wniosku': 'termin_wniosku',
                  'termin_wyplaty': 'termin_wyplaty', 'okres_kwoty': 'okres_kwoty'}
DENOMINACJA = '1995-01-01'   # 10 000 starych zł = 1 nowy zł: kwot sprzed tej daty nie porównuje się bez przeliczenia


def kwota_z_wyrazenia(wyrazenie):
    """Jedna kwota w wyrażeniu reguły („14000 zł”, „1 978,49 zł”) albo None (wzór, kilka kwot, procent)."""
    kw = re.findall(r'(?<![\d,.])(\d{1,3}(?:[  .]\d{3})+|\d+)(?:,(\d{1,2}))?\s*zł', str(wyrazenie or ''))
    if len(kw) != 1 or '%' in str(wyrazenie):
        return None
    cale, gr = kw[0]
    return '{}.{}'.format(re.sub(r'[  .]', '', cale), (gr or '00').ljust(2, '0'))


def karty_analiz_eli(socjal, na_dzien, benefits, extra_karty, akty_meta, pomijane_akty):
    """Analizy ELI (`Analizy ELI/<KOD>/dane`, schemat 0.1) → karty strony: świadczenie (co) i adresat (komu),
    reguły kwot (kwota, ryczałt → oś czasu i kwota aktualna; procent, wzór → formuła; limit, minimum → progi),
    parametry świadczenia → progi, okresy → do kiedy, wersje warunków i warianty → warunki, ustalenia → trasa dowodów.
    Zwraca zbiór ELI opublikowanych w ten sposób (dla nich karty automatu skryptu mapy są pomijane)."""
    katalog = socjal / 'Analizy ELI'
    opublikowane = set()
    for p_stan in sorted(katalog.glob('DU-*/dane/stan.json')) if katalog.is_dir() else []:
        stan = wczytaj(p_stan)
        eli = stan.get('eli')
        if stan.get('status') not in STATUSY_ANALIZ_ELI or not ELI_RE.fullmatch(str(eli)) or eli in pomijane_akty:
            continue
        d = p_stan.parent
        czyt = lambda nazwa, klucz: (wczytaj(d / nazwa).get(klucz, []) if (d / nazwa).is_file() else [])
        sw, ust = czyt('swiadczenia.json', 'swiadczenia'), {u['id']: u for u in czyt('ustalenia.json', 'ustalenia')}
        reguly, parametry, okresy = czyt('reguly_kwot.json', 'reguly'), czyt('parametry.json', 'parametry'), czyt('okresy.json', 'okresy')
        wersje, warianty = czyt('wersje_warunkow.json', 'wersje'), czyt('warianty.json', 'warianty')
        if not sw:
            continue

        def dowod_u(uid):
            u = ust.get(uid) or {}
            src = u.get('akt_eli') or u.get('dokument_eli')
            if not (ELI_RE.fullmatch(str(src)) and u.get('cytat')):
                return None
            x = dowod(src, u.get('jednostka'), u['cytat'], (u.get('wersja') or {}).get('stan_na'))
            for a, b in (('zrodlo_sha256', '_sha256'), ('strona_pdf', '_strona')):
                if u.get(a) is not None:
                    x[b] = u[a]
            return x

        def pierwszy_dowod(uids):
            return next((x for x in (dowod_u(i) for i in uids or []) if x), None)

        stan_tekstu = next((data_tekstu((u.get('wersja') or {}).get('stan_na')) for u in ust.values()
                            if u.get('akt_eli') == eli and (u.get('wersja') or {}).get('stan_na')), None)
        meta_us = socjal.parent / 'Ustawy_Socjale' / eli.replace('/', '_') / 'metadane.json'
        m_us = wczytaj(meta_us) if meta_us.is_file() else {}
        w_mocy = m_us.get('inForce') == 'IN_FORCE'
        akty_meta.setdefault(eli, {'tytul': m_us.get('title') or 'Akt ' + eli, 'stan': stan_tekstu, 'tryb': 'analiza_eli'})
        for s in sw:
            prz = pierwszy_dowod(s.get('ustalenia'))
            if not prz or not s.get('id') or not s.get('nazwa'):
                continue
            bid = slug(s['id'].replace('/', '-')).upper()
            rodzaj = (s.get('rodzaj') or '').lower()
            koniec = data_tekstu(s.get('okres_do'))
            k = {'id': bid, 'slug': bid.lower(), 'nazwa': s['nazwa'],
                 'rodzaj_korzysci': ('dofinansowanie' if rodzaj.startswith('finansowanie') else 'zwolnienie' if rodzaj in ('ulga', 'zwolnienie')
                                     else 'uprawnienie' if rodzaj.startswith(('ochrona', 'wylaczenie', 'umorzenie', 'mechanizm', 'sposob'))
                                     else 'swiadczenie_rzeczowe' if s.get('forma') == 'niepieniezne'
                                     else 'swiadczenie_jednorazowe' if 'jednoraz' in (s.get('opis') or '').lower() + s['nazwa'].lower()
                                     else 'swiadczenie_okresowe'),
                 # „obowiązuje” tylko dla zwykłego świadczenia bez daty końca w obowiązującej ustawie; warianty z innych
                 # aktów (np. COVID-19) i jednorazowe przeliczenia bez daty końca: do ustalenia
                 'status': ('zamknieta' if koniec and koniec < na_dzien
                            else 'obowiazuje' if rodzaj == 'swiadczenie' and not koniec and w_mocy
                            else 'do_ustalenia'),
                 'komu': s.get('adresat') or 'Krąg uprawnionych nieustalony w analizie.',
                 'opis_prosty': s.get('opis'), 'sytuacje': [], 'sytuacje_zrodlo': None,
                 'przepis': prz, 'ile': bez_kwoty(), 'do_kiedy': [], 'powiazane': [],
                 # tekst stały wg schematu strony; pochodzenie karty (Analizy ELI) jest w extra_karty['pochodzenie']
                 'stan': {'data_stanu': prz['data_stanu'] or stan_tekstu or na_dzien, 'tekst': 'tekst ujednolicony (informacyjny)'},
                 'nieustalone': [], 'flagi': []}
            ile = k['ile']
            # --- ile: reguły kwot świadczenia
            r_s = sorted([r for r in reguly if r.get('swiadczenie') == s['id']], key=lambda r: (r.get('od') or '', r['id']))
            kwotowe = [(r, kwota_z_wyrazenia(r.get('wyrazenie'))) for r in r_s if r.get('typ') in ('kwota', 'ryczalt')]
            kwotowe = [(r, w) for r, w in kwotowe if w]
            for od in sorted({r.get('od') for r, _ in kwotowe}, key=lambda x: x or ''):
                grupa = [(r, w) for r, w in kwotowe if r.get('od') == od]
                dw = pierwszy_dowod([u for r, _ in grupa for u in r.get('ustalenia') or []]) or prz
                stare = bool(od and od < DENOMINACJA)
                tekst = lambda w: zlote(w) + (' (stare złote, przed denominacją 1.01.1995)' if stare else '')
                jedna = len(grupa) == 1
                ile['os_czasu'].append({'wartosc': tekst(grupa[0][1]) if jedna else None,
                                        'warianty': None if jedna else [{'etykieta': r['nazwa'], 'wartosc': tekst(w)} for r, w in grupa],
                                        'od': data_tekstu(od), 'do': data_tekstu(grupa[0][0].get('do')),
                                        'rodzaj_zmiany': 'pierwszy_znany_wpis' if not ile['os_czasu'] else 'nowelizacja',
                                        'poprzednia': None, 'roznica': None, 'dowod': dw})
            if ile['os_czasu']:
                ile['rozwiazanie'] = 'kwota_w_ustawie'
                biezace = [w for w in ile['os_czasu'] if w['od'] and w['od'] <= na_dzien and (w['do'] is None or w['do'] >= na_dzien)]
                if len(biezace) == 1 and not (biezace[0]['od'] < DENOMINACJA):
                    x = biezace[0]
                    ile['aktualna'] = {'wartosc': x['wartosc'], 'warianty': x['warianty'], 'od': x['od'], 'do': x['do']}
            wzory = [r for r in r_s if r.get('typ') in ('wzor', 'procent')]
            if wzory and not ile['aktualna']:
                ile['rozwiazanie'] = ile['rozwiazanie'] if ile['os_czasu'] else 'formula'
                ile['regula'] = {'udzial': None, 'podstawa_id': None,
                                 'opis': '; '.join('{}: {}'.format(r['nazwa'], r['wyrazenie']) for r in wzory)[:900]}
            for r in [r for r in r_s if r.get('typ') in ('limit', 'minimum')]:
                ile['progi'].append({'przepis': '{} — {}'.format(r['nazwa'], r.get('wyrazenie')),
                                     'wpisy': [{'wartosc': zlote(kwota_z_wyrazenia(r['wyrazenie'])) if kwota_z_wyrazenia(r['wyrazenie']) else str(r['wyrazenie'])[:200],
                                                'warianty': None, 'od': data_tekstu(r.get('od')), 'do': data_tekstu(r.get('do')),
                                                'rodzaj_zmiany': 'pierwszy_znany_wpis', 'poprzednia': None, 'roznica': None,
                                                'dowod': pierwszy_dowod(r.get('ustalenia')) or prz}]})
            # --- progi: parametry świadczenia (np. progi dochodowe, kwoty minimalne) z historią
            serie = defaultdict(list)
            for x in parametry:
                if x.get('swiadczenie') == s['id'] and x.get('wartosc') is not None:
                    serie[(x.get('seria'), x.get('nazwa'))].append(x)
            for (seria, nazwa), wpisy in serie.items():
                wpisy.sort(key=lambda x: x.get('od') or '')
                rows = []
                for x in wpisy:
                    po = x.get('pochodzenie') or {}
                    dw = (dowod(po['eli'], po.get('przepis'), po.get('cytat') or x.get('nazwa')) if ELI_RE.fullmatch(str(po.get('eli')))
                          else pierwszy_dowod(x.get('ustalenia'))) or prz
                    rows.append({'wartosc': zlote(x['wartosc']) if 'PLN' in str(x.get('jednostka')) else str(x['wartosc']),
                                 'warianty': None, 'od': data_tekstu(x.get('od')), 'do': data_tekstu(x.get('do')),
                                 'rodzaj_zmiany': 'pierwszy_znany_wpis' if not rows else 'waloryzacja',
                                 'poprzednia': rows[-1]['wartosc'] if rows else None, 'roznica': None, 'dowod': dw,
                                 '_charakter': x.get('charakter')})
                ile['progi'].append({'przepis': nazwa or seria, 'wpisy': rows})
            if not (ile['os_czasu'] or ile['regula'] or ile['progi']):
                k['nieustalone'].append(nieustalone('ile', 'Analiza nie podaje kwoty ani reguły kwoty dla tego świadczenia.'))
            ile['trasa'] = [{'krok': i + 1, 'opis': (ust[u].get('tresc') or 'ustalenie')[:240], 'dowod': x}
                            for i, (u, x) in enumerate((u, dowod_u(u)) for u in (s.get('ustalenia') or [])[:10] if dowod_u(u))]
            # --- do kiedy i warunki
            for o in [o for o in okresy if o.get('swiadczenie') == s['id']]:
                dw = pierwszy_dowod(o.get('ustalenia')) or prz
                if o.get('rodzaj') in TERMINY_ANALIZ:
                    row = {'rodzaj': TERMINY_ANALIZ[o['rodzaj']], 'data': data_tekstu(o.get('od')),
                           'opis': ' — '.join(x for x in (o.get('tresc'), o.get('regula')) if x), 'skutek': None, 'dowod': dw}
                    for f in ('od', 'do'):
                        if o.get(f): row[f] = data_tekstu(o[f])
                    k['do_kiedy'].append(row)
                else:
                    k['powiazane'].append({'typ': 'warunek', 'cytat': '{}: {}'.format(o.get('rodzaj'), o.get('tresc'))})
            if koniec:
                k['do_kiedy'].append({'rodzaj': 'granica_przepisu', 'data': koniec, 'opis': 'Świadczenie przysługiwało do {}.'.format(koniec),
                                      'skutek': None, 'dowod': prz})
            for v in [v for v in wersje if v.get('swiadczenie') == s['id']]:
                k['powiazane'].append({'typ': 'warunek', 'cytat': '{}: {} (od {} do {})'.format(
                    v.get('element'), v.get('tresc'), v.get('od') or '?', v.get('do') or 'nadal')})
            for w in [w for w in warianty if w.get('swiadczenie') == s['id']]:
                k['powiazane'].append({'typ': 'warunek', 'cytat': 'Wariant: {}'.format(w.get('nazwa'))})
            benefits.append(k)
            extra_karty[bid] = {'pochodzenie': 'reczna_ELI', 'zrodlo_id': s['id'], 'rodzaj_zrodlowy': rodzaj,
                                'status_zrodlowy': stan.get('status'), 'analiza': d.parent.relative_to(socjal).as_posix(),
                                'artykuly': sorted({a for a in (art_z_przepisu(eli, (ust.get(u) or {}).get('jednostka'))
                                                                for u in s.get('ustalenia') or []) if a}),
                                'jednostki': [], 'historia_parametr': None, 'uwaga_czasowa': None,
                                'odsylacze_do_sprawdzenia': None, 'nadrzedne': s.get('nadrzedne')}
            opublikowane.add(eli)
    return opublikowane


def generuj(socjal: Path, wynik: Path, na_dzien: str):
    for paczka in PACZKI_RECZNE:
        for relative in (paczka['karty'], paczka['historia']):
            if paczka['wymagana'] and not (socjal / relative).is_file():
                raise BladSocjal('Nie ma wymaganego pliku: {}'.format(socjal / relative))
    if not data_tekstu(na_dzien):
        raise BladSocjal('Błędne --na-dzien, wymagane YYYY-MM-DD.')
    # Rejestr norm zawiera *jednostki*, a nie 1:1 świadczenia.
    akty_meta, jednostki = {}, {}
    artykuly = {}
    for kat in sorted((socjal / 'Dane/Mapa').glob('DU-*')):
        przebieg, js = kat / 'przebieg.json', kat / 'jednostki.json'
        if not (przebieg.is_file() and js.is_file()):
            continue
        meta = wczytaj(przebieg)
        eli = meta.get('akt')
        if not ELI_RE.fullmatch(str(eli)):
            raise BladSocjal('Niepoprawny akt w {}'.format(przebieg))
        stan = data_tekstu((meta.get('zrodlo') or {}).get('data_stanu'))
        akty_meta[eli] = {'tytul': meta.get('tytul') or 'Akt ' + eli, 'stan': stan,
                          'tryb': (meta.get('konfiguracja_aktu') or {}).get('tryb')}
        items = wczytaj(js)
        for u in items:
            uid = u.get('id')
            if not uid or uid in jednostki:
                raise BladSocjal('Powtórzony albo pusty identyfikator jednostki: {}'.format(uid))
            jednostki[uid] = u
            art_id = przepis_art_id(eli, uid)
            if not art_id: continue
            art = artykuly.setdefault(art_id, {'id': art_id, 'eli': eli,
                                               'artykul': ART_RE.search(uid).group(1).lstrip('0') or '0',
                                               'stan_tekstu': stan, 'jednostki': [],
                                               'powiazane_artykuly': [], 'powiazane_akty': [], 'korzysci': []})
            if u.get('tekst') and len(art['jednostki']) < 150:
                art['jednostki'].append({'id': uid, 'przepis': u.get('sciezka') or 'Jednostka',
                                         'tekst': u['tekst'], 'role': u.get('role') or [],
                                         'rodzic': u.get('rodzic'), 'dzieci': u.get('dzieci') or []})
            # Odesłania do innych aktów zachowujemy jako źródłowe cytowania.
            # Nie traktujemy ELI tekstu jednolitego jako dowodu, że określone
            # świadczenie zostało przyznane przez ten właśnie akt.
            for od in u.get('odeslania_zewnetrzne') or []:
                target = od.get('eli_glowne')
                if ELI_RE.fullmatch(str(target)):
                    item = {'eli': target, 'akt_tytul': od.get('akt_tytul'),
                            'cytat': od.get('cytat'), 'z_pozn_zm': bool(od.get('z_pozn_zm'))}
                    if item not in art['powiazane_akty']:
                        art['powiazane_akty'].append(item)
            for od in u.get('odeslania_wewnetrzne') or []:
                if od.get('zewnetrzne') or not od.get('cel'): continue
                target = przepis_art_id(eli, od['cel'])
                if target and target != art_id and target not in art['powiazane_artykuly']:
                    art['powiazane_artykuly'].append(target)
    # Publikujemy dokładnie karty strukturalne; nie przenosimy prywatnych ścieżek
    # dyskowych ani magazynu historii projektu Obsidian.
    historia = historie_reczne(socjal)
    wielkosci = wczytaj_wielkosci(socjal)
    benefits = []
    extra_karty = {}
    aliasy = {}
    pomin = {(p['akt'], n): powod for p in PACZKI_RECZNE for n, powod in p.get('pomin', {}).items()}
    for paczka in PACZKI_RECZNE:
        if (socjal / paczka['karty']).is_file():
            karty_paczki(socjal, paczka, historia, jednostki, na_dzien, benefits, extra_karty, aliasy)
    # analizy AI (Analizy ELI): ręczne paczki FUS i SW mają pierwszeństwo; dla pozostałych aktów analiza
    # zastępuje karty automatu skryptu mapy tej samej ustawy
    analizy_eli = karty_analiz_eli(socjal, na_dzien, benefits, extra_karty, akty_meta, {p['akt'] for p in PACZKI_RECZNE})
    # Dokładna nazwa (z pominięciem dopisku w nawiasie) i ten sam akt.
    # Nie utożsamiamy np. „opieki” z wcześniejszą emeryturą opiekuna.
    nazwa_klucz = lambda n: ' '.join(re.sub(r'\([^)]*\)', '', n).casefold().split())
    reczne = {(k['przepis']['eli'], nazwa_klucz(k['nazwa'])): k for k in benefits}
    reczne.update({(eli, nazwa_klucz(n)): k for (eli, n), k in aliasy.items()})
    pominiete = []
    for katalog in sorted((socjal / 'Dane/Mapa').glob('DU-*')):
        kp = katalog / 'korzysci.json'
        if not kp.is_file(): continue
        for src in wczytaj(kp).get('korzysci', []):
            if not src.get('id') or not src.get('nazwa'):
                continue
            bid = src['id']
            if not re.fullmatch(r'[A-Za-z0-9-]+', bid):
                raise BladSocjal('Niebezpieczny id karty: ' + bid)
            if src.get('tylko_katalog') or src.get('nazwa_ogolna'):
                # Materiały ogólnikowe nie są świadczeniami.
                continue
            eli = src.get('akt')
            if not ELI_RE.fullmatch(str(eli)):
                raise BladSocjal('Błędny ELI automatycznej karty: ' + bid)
            if eli in analizy_eli:
                pominiete.append({'id': bid, 'karta_reczna': None, 'powod': 'Ustawa ma sprawdzoną analizę w Analizy ELI.'})
                continue
            if (eli, nazwa_klucz(src['nazwa'])) in pomin:
                pominiete.append({'id': bid, 'karta_reczna': None, 'powod': pomin[(eli, nazwa_klucz(src['nazwa']))]})
                continue
            manual = reczne.get((eli, nazwa_klucz(src['nazwa'])))
            if manual and akty_meta.get(eli, {}).get('tryb') == 'porownanie':
                # Zachowaj dodatkowe terminy i odsyłacze na ręcznej karcie.
                przenies_terminy(src, manual, jednostki)
                if not manual['ile']['os_czasu']:
                    przenies_podsumowanie(src, manual, jednostki, na_dzien)
                przenies_limity(src, manual, wielkosci)
                pominiete.append({'id': bid, 'karta_reczna': manual['id'],
                                  'powod': 'Ta sama nazwa i akt w trybie porownanie.'})
                refs = [r.get('jednostka') for r in src.get('przepisy_przyznajace') or [] if r.get('jednostka')]
                extra = extra_karty[manual['id']]
                extra['jednostki'] = sorted(set(extra['jednostki'] + refs))
                extra['artykuly'] = sorted(set(extra['artykuly']) | {
                    a for a in (przepis_art_id(eli, r) for r in refs) if a})
                continue
            refs = src.get('przepisy_przyznajace') or []
            selected = refs[0] if refs else (src.get('wzmianki') or [{}])[0]
            uid = selected.get('jednostka')
            unit = jednostki.get(uid) or {}
            quote = unit.get('tekst') or (src.get('komu') or {}).get('cytat') or 'Nie ustalono treści przepisu przyznającego.'
            pr = dowod(eli, selected.get('sciezka') or unit.get('sciezka') or 'Jednostka nieustalona',
                       quote, akty_meta.get(eli, {}).get('stan'))
            typ = src.get('rodzaj_korzysci') or 'uprawnienie'
            if typ not in ('swiadczenie_okresowe', 'swiadczenie_jednorazowe', 'ulga_podatkowa',
                           'zwolnienie', 'swiadczenie_rzeczowe', 'uprawnienie', 'dofinansowanie'):
                typ = 'uprawnienie'
            status = src.get('status')
            if status not in ('obowiazuje', 'zamknieta', 'do_ustalenia'):
                status = 'do_ustalenia'
            opis = (src.get('komu_krotko') or {}).get('tekst') or (src.get('komu') or {}).get('cytat') or ''
            k = {'id': bid, 'slug': bid.lower(), 'nazwa': src['nazwa'],
                 'rodzaj_korzysci': typ, 'status': status, 'komu': opis,
                 'opis_prosty': None, 'sytuacje': [x for x in src.get('sytuacje', [])
                    if x in ('dziecko','ciaza_porod','niepelnosprawnosc','opieka_nad_bliskim',
                             'senior','niski_dochod','utrata_pracy','mieszkanie_energia','edukacja','cudzoziemiec')],
                 'sytuacje_zrodlo': 'automatyczne', 'przepis': pr, 'ile': bez_kwoty(),
                 'do_kiedy': [], 'powiazane': [],
                 'stan': {'data_stanu': akty_meta.get(eli, {}).get('stan') or na_dzien,
                          'tekst': 'tekst ujednolicony (informacyjny)'},
                 'nieustalone': [],
                 'flagi': ['Kandydat automatyczny. Nie stanowi potwierdzenia prawa do świadczenia.']}
            przenies_terminy(src, k, jednostki)
            podsumowanie_kwoty = przenies_podsumowanie(src, k, jednostki, na_dzien)
            # Stara heurystyka jest wyłącznie awaryjna: nie zastępuje podsumowania
            # i nie przedstawia nominalnej kwoty z przypisem jako aktualnej.
            stawki = [x for x in src.get('ile', []) if x.get('rodzaj') == 'kwota_w_ustawie' and x.get('tekst')]
            if len(stawki) == 1 and not podsumowanie_kwoty and not any(
                    nominalna_zastepowana(q, jednostki) for q in src.get('ile') or []):
                q = stawki[0]
                cytat = str(q.get('cytat') or '')
                if src['nazwa'].lower() in cytat.lower() and re.search(r'\bwynosi\b', cytat, re.I):
                    kw = q['tekst']
                    d = dowod(eli, q.get('sciezka'), cytat, k['stan']['data_stanu'])
                    k['ile']['rozwiazanie'] = 'kwota_w_ustawie'
                    k['ile']['aktualna'] = {'wartosc': kw, 'od': None, 'do': None, 'warianty': None}
                    k['ile']['os_czasu'] = [{'wartosc': kw, 'warianty': None,
                        'od': None, 'do': None, 'rodzaj_zmiany': 'pierwszy_znany_wpis',
                        'poprzednia': None, 'roznica': None, 'dowod': d}]
            przenies_obliczona(src, k, jednostki, wielkosci, na_dzien)
            przenies_limity(src, k, wielkosci)
            if not k['ile']['aktualna'] and not k['ile']['wyliczenie']:
                k['nieustalone'].append(nieustalone('ile', 'Kwota nie została jednoznacznie potwierdzona w danych wejściowych.'
                    + (' Podano limit kwoty z przepisu (sekcja progów i limitów).' if k['ile']['progi'] else '')))
            for field, typ_rel in [('warunki', 'warunek'), ('wylaczenia', 'wykluczenie')]:
                for rel in (src.get(field) or [])[:50]:
                    quote = rel.get('cytat') or ''
                    if quote:
                        k['powiazane'].append({'typ': typ_rel, 'cytat': quote,
                                              'przepis': rel.get('sciezka') or 'Jednostka źródłowa'})
            benefits.append(k)
            wszystkich = []
            for field in ('przepisy_przyznajace', 'wzmianki', 'warunki', 'wylaczenia'):
                wszystkich.extend(x['jednostka'] for x in src.get(field, []) if x.get('jednostka'))
            article_refs = sorted({przepis_art_id(eli, x) for x in wszystkich} - {None})
            extra_karty[bid] = {'pochodzenie': 'automat', 'zrodlo_id': bid,
                 'rodzaj_zrodlowy': src.get('rodzaj_korzysci'),
                 'status_zrodlowy': src.get('status_weryfikacji'),
                 'artykuly': article_refs, 'jednostki': sorted(set(wszystkich)),
                 'historia_parametr': None, 'sporne': src.get('sporne') or [],
                 'nieustalone_zrodla': src.get('nieustalone') or [],
                 'kwalifikacja_automatu': src.get('kwalifikacja')}
    uzupelnij_notatkami(socjal, benefits, extra_karty, na_dzien)
    przenies_wyliczenia(socjal, benefits, wielkosci, na_dzien)
    benefits, poza_mapa = kwalifikuj_do_mapy(socjal, benefits, extra_karty)
    zastosuj_standard(socjal, benefits)
    if not benefits: raise BladSocjal('Brak kart do publikacji.')
    ids = [b['id'] for b in benefits]
    if len(ids) != len(set(ids)):
        raise BladSocjal('Powtórzone identyfikatory świadczeń w obu źródłach.')
    for bid, meta in extra_karty.items():
        for art_id in meta['artykuly']:
            if art_id in artykuly:
                artykuly[art_id]['korzysci'].append(bid)
    # Nie publikuj niedziałających odnośników: odwołania tylko do znanych artykułów.
    for art in artykuly.values():
        art['powiazane_artykuly'] = [x for x in art['powiazane_artykuly'] if x in artykuly]
        art['korzysci'] = sorted(set(art['korzysci']))
    # Powiązania karta -> akt -> karta; dodatkowo ręczna mapa artykułów.
    akt_benefits = defaultdict(list)
    act_eli = set(akty_meta)
    for b in benefits:
        eli = b['przepis']['eli']
        akt_benefits[eli].append(b['id']);act_eli.add(eli)
        for ref in b['ile']['trasa']:
            act_eli.add(ref['dowod']['eli'])
        for row in b['ile']['os_czasu']:
            act_eli.add(row['dowod']['eli'])
        for row in b['do_kiedy']:
            act_eli.add(row['dowod']['eli'])
    pliki_pdf = pliki_aktow(socjal)
    # akty z Analiz ELI: teksty ustawy z dokumenty.json w Ustawy_Socjale (adres w API, SHA-256, rozmiar)
    for eli in analizy_eli - set(pliki_pdf):
        p_dok = socjal.parent / 'Ustawy_Socjale' / eli.replace('/', '_') / 'dokumenty.json'
        for x in (wczytaj(p_dok).get('dokumenty', []) if p_dok.is_file() else []):
            if x.get('grupa') == 'Tekst aktu' and x.get('typ') in ('U', 'O') and str(x.get('nazwa_api', '')).lower().endswith('.pdf'):
                # tekst ujednolicony wymaga daty stanu: ta z analizy (tekst, na którym ją wykonano); bez niej pomijamy plik
                stan_u = (akty_meta.get(eli) or {}).get('stan') if x['typ'] == 'U' else None
                if x['typ'] == 'U' and not stan_u:
                    continue
                kod = eli.replace('/', '-')
                pliki_pdf.setdefault(eli, []).append({
                    'rodzaj': x['typ'], 'plik': 'akty/{}/{}'.format(kod, x['nazwa_api']),
                    'nazwa_pobierania': '{}_{}.pdf'.format(kod, 'tekst-ujednolicony' if x['typ'] == 'U' else 'tekst-ogloszony'),
                    'sha256': x['sha256'], 'rozmiar': int(x['rozmiar']), 'url_zrodla': x['url'], 'pobrano': x.get('pobrano'),
                    'data_stanu': stan_u, 'eli_obwieszczenia': None, 'uzyty_w_danych': True, 'zrodlo': 'API Sejmu (ELI)'})
    acts = []
    for eli in sorted(act_eli):
        m = akty_meta.get(eli, {})
        acts.append({'eli': eli, 'tytul': m.get('tytul') or 'Akt prawny {}'.format(eli),
          'typ': 'Ustawa' if eli in akty_meta else 'Akt prawny', 'data_stanu': m.get('stan'),
          'url_eli': eli_url(eli), 'url_isap': None, 'korzysci': sorted(set(akt_benefits[eli])),
          'wykonawcze': [], 'status': 'Stan prawny należy zweryfikować u źródła', 'pliki': pliki_pdf.get(eli, [])})
    slowniki = {'rodzaj_korzysci': {'swiadczenie_okresowe':'świadczenie okresowe',
            'swiadczenie_jednorazowe':'świadczenie jednorazowe','ulga_podatkowa':'ulga podatkowa',
            'zwolnienie':'zwolnienie','swiadczenie_rzeczowe':'świadczenie rzeczowe',
            'uprawnienie':'uprawnienie / mechanizm','dofinansowanie':'dofinansowanie'},
        'rodzaj_terminu': {'okres_kwoty':'okres obowiązywania kwoty','termin_wniosku':'termin złożenia wniosku',
            'granica_przepisu':'zmiana albo koniec przepisu','okres_zasilkowy':'okres przyznania prawa',
            'harmonogram_dostepnosci':'otwieranie prawa etapami','termin_wyplaty':'termin wypłaty',
            'termin_dokumentu':'termin dostarczenia dokumentu', 'termin_organu':'termin działania organu',
            'termin_inny':'inny termin z przepisu', 'wejscie_w_zycie':'wejście w życie'},
        'status': {'obowiazuje':'obowiązuje (według źródła)', 'zamknieta':'zamknięta',
                   'do_ustalenia':'do ustalenia'},
        'sytuacje': {'dziecko':'dziecko','ciaza_porod':'ciąża i poród',
           'niepelnosprawnosc':'niepełnosprawność','opieka_nad_bliskim':'opieka nad bliskim',
           'senior':'senior','niski_dochod':'niski dochód','utrata_pracy':'utrata pracy',
           'mieszkanie_energia':'mieszkanie i energia','edukacja':'edukacja', 'cudzoziemiec':'cudzoziemiec'}}
    extras = {'kontrakt': 'socjal-1', 'na_dzien': na_dzien,
              'karty': extra_karty, 'artykuly': sorted(artykuly.values(), key=lambda a: a['id']),
              'historia': historia, 'pominiete_duplikaty': pominiete, 'poza_mapa': poza_mapa,
              'statystyki': {'reczne': sum(v['pochodzenie'].startswith('reczna_') for v in extra_karty.values()),
                            'automatyczne': sum(v['pochodzenie']=='automat' for v in extra_karty.values()),
                            'z_notatek': sum(v['pochodzenie']=='notatka' for v in extra_karty.values())}}
    zapis(wynik / 'korzysci.json', benefits)
    zapis(wynik / 'akty.json', acts)
    zapis(wynik / 'slowniki.json', slowniki)
    zapis(wynik / 'socjal.json', extras)
    (wynik / 'akty').mkdir(parents=True, exist_ok=True)
    (wynik / 'akty/SHA256SUMS').write_text(''.join(
        '{}  {}\n'.format(d['sha256'], d['plik'].removeprefix('akty/')) for a in acts for d in a['pliki']), encoding='utf-8')
    manifest = {'kontrakt': KONTRAKT, 'wygenerowano': datetime.now(timezone.utc).isoformat(),
                'wersja_kodu': 'importuj_socjal-1.6', 'na_dzien': na_dzien,
                'pliki': {f: sha(wynik / f) for f in PODSTAWOWE},
                'zakres': sorted(akty_meta),
                'liczby': {'korzysci': len(benefits), 'akty': len(acts), 'pliki_aktow': sum(len(a['pliki']) for a in acts)},
                'z_plikami_pdf': False}
    # Sidecar też jest integralnie weryfikowany przy imporcie Pythona.
    manifest['pliki']['socjal.json'] = sha(wynik / 'socjal.json')
    zapis(wynik / 'manifest.json', manifest)
    print('Socjal: {} kart ({} ręcznych, {} automatów), {} aktów, {} artykułów, {} grup historii.'.format(
      len(benefits), extras['statystyki']['reczne'], extras['statystyki']['automatyczne'],
      len(acts), len(artykuly), len(historia)))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--socjal', required=True, type=Path, help='Główny folder sejfu Socjal.')
    parser.add_argument('--wyjscie', required=True, type=Path, help='Katalog wynikowy kontraktu Astro.')
    parser.add_argument('--na-dzien', default=datetime.now().date().isoformat())
    args = parser.parse_args()
    try:
        generuj(args.socjal.expanduser().resolve(), args.wyjscie.expanduser().resolve(), args.na_dzien)
    except (BladSocjal, OSError, ValueError) as error:
        parser.exit(1, 'BŁĄD SOCJAL: {}\n'.format(error))

if __name__ == '__main__': main()
