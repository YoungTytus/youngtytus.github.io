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


def nieustalone(pole, opis):
    return {'pole': pole, 'powod': opis}


def zrodlo_fus(k):
    z = k['zrodla'][0]
    ident = z.get('id_jednostki', '')
    eli = ident.split('#')[0] if '#' in ident else 'DU/1998/1118'
    return dowod(eli, z.get('przepis'), z.get('cytat'), z.get('stan_pdf'))


def historie_fus(root, dzien):
    sciezka = root / 'Dane/FUS/history_all_verified.json'
    raw = wczytaj(sciezka) if sciezka.is_file() else []
    parametry = defaultdict(list)
    for i, p in enumerate(raw):
        if not p.get('parametr') or not data_tekstu(p.get('od')):
            continue
        src = p.get('source') or {}
        if not ELI_RE.fullmatch(str(src.get('eli', ''))):
            continue
        parametry[p['parametr']].append({
            'parametr': p['parametr'], 'od': data_tekstu(p['od']), 'do': data_tekstu(p.get('do')),
            'wartosc': p.get('wartosc'), 'jednostka': p.get('jednostka'),
            'typ': p.get('typ'), 'dowod': dowod(src['eli'], src.get('przepis'), src.get('cytat')),
            'wyliczona': str(p.get('typ') or '').startswith('kwota_obliczona'),
            'status': p.get('status'),
        })
    for p in parametry.values():
        p.sort(key=lambda v: (v['od'], v['typ'] or ''))
    return dict(sorted(parametry.items()))


def kwota_z_historii(b, hist, param, dzien):
    rekordy = hist.get(param, [])
    for h in rekordy:
        try:
            kwota = '{:.2f} zł'.format(Decimal(str(h['wartosc'])).quantize(Decimal('0.01')))
        except (InvalidOperation, ValueError, TypeError):
            continue
        wpis = {'wartosc': kwota, 'warianty': None, 'od': h['od'], 'do': h['do'],
                'rodzaj_zmiany': 'pierwszy_znany_wpis' if not b['ile']['os_czasu'] else 'waloryzacja',
                'poprzednia': None, 'roznica': None, 'dowod': h['dowod']}
        b['ile']['os_czasu'].append(wpis)
    if b['ile']['os_czasu']:
        b['ile']['rozwiazanie'] = 'kwota_w_ustawie' if not any(h['wyliczona'] for h in rekordy) else 'nieustalone'
        current = [w for w in b['ile']['os_czasu'] if w['od'] <= dzien and (w['do'] is None or w['do'] >= dzien)]
        # Nie wyciągamy aktualnej kwoty z kilku nakładających się wersji.
        if len(current) == 1:
            x = current[0]
            b['ile']['aktualna'] = {'wartosc': x['wartosc'], 'warianty': None, 'od': x['od'], 'do': x['do']}
        elif len(current) > 1:
            b['nieustalone'].append(nieustalone('ile.aktualna', 'Znaleziono nakładające się okresy historii, wymagany przegląd.'))


def rodzaj_fus(k):
    nazwa = (k.get('rodzaj') or '').lower()
    if 'jednorazowe' in nazwa:
        return 'swiadczenie_jednorazowe'
    if k['id'] in ('c_zwolnienie_oplat', 'c_bezplatne_poswiadczenia'):
        return 'zwolnienie'
    if nazwa in ('mechanizm_podwyzszenia', 'mechanizm_zbiegu', 'zwiekszenie_swiadczenia') or k['id'].startswith('c_'):
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
        if extras[k['id']]['pochodzenie'] == 'reczna_FUS':
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


def generuj(socjal: Path, wynik: Path, na_dzien: str):
    wymagane = ('Dane/FUS/karty.json', 'Dane/FUS/history_all_verified.json')
    for relative in wymagane:
        if not (socjal / relative).is_file():
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
        akty_meta[eli] = {'tytul': meta.get('tytul') or 'Akt ' + eli, 'stan': stan}
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
    historia = historie_fus(socjal, na_dzien)
    benefits = []
    extra_karty = {}
    for karta in wczytaj(socjal / 'Dane/FUS/karty.json'):
        if not karta.get('id') or not karta.get('zrodla'):
            raise BladSocjal('Karta FUS bez id albo źródeł.')
        bid = 'FUS-' + slug(karta['id'])
        proven = zrodlo_fus(karta)
        k = {'id': bid, 'slug': bid.lower(), 'nazwa': karta['nazwa'],
             'rodzaj_korzysci': rodzaj_fus(karta), 'status': 'do_ustalenia',
             'komu': karta.get('komu') or 'Krąg uprawnionych nieustalony w karcie.',
             'opis_prosty': None, 'sytuacje': [], 'sytuacje_zrodlo': None,
             'przepis': proven, 'ile': bez_kwoty(), 'do_kiedy': [], 'powiazane': [],
             'stan': {'data_stanu': proven['data_stanu'] or na_dzien, 'tekst': 'tekst ujednolicony (informacyjny)'},
             'nieustalone': [], 'flagi': ['Opracowanie ręczne; historia uprawnień może być niepełna.']}
        for typ, key in [('warunek', 'warunki'), ('wykluczenie', 'wykluczenia')]:
            for txt in karta.get(key) or []:
                if txt: k['powiazane'].append({'typ': typ, 'cytat': str(txt)})
        # Formuła nie jest kwotą w PLN; zapisujemy ją jako wskazówkę do przeglądu.
        k['nieustalone'].append(nieustalone('ile.regula_kwoty', karta.get('regula_kwoty') or 'Brak formuły kwoty.'))
        k['ile']['trasa'] = [
            {'krok': i + 1, 'opis': 'Źródło karty: {}'.format(z.get('przepis') or 'jednostka'),
             'dowod': dowod(z.get('id_jednostki', 'DU/1998/1118').split('#')[0],
                            z.get('przepis'), z.get('cytat'), z.get('stan_pdf'))}
            for i, z in enumerate(karta['zrodla']) if z.get('id_jednostki', '').split('#')[0] and z.get('cytat')
        ]
        przypisanie = {'zasilek_pogrzebowy': 'zasilek_pogrzebowy_limit',
                       'dodatek_pielegnacyjny': 'dodatek_pielegnacyjny',
                       'dodatek_sierota_zupelna': 'dodatek_sierota_zupelna'}.get(karta['id'])
        if przypisanie:
            kwota_z_historii(k, historia, przypisanie, na_dzien)
            # Zmienność przepisów ma pierwszeństwo nad niezależnym domniemaniem bieżącego prawa.
            if k['ile']['aktualna']:
                k['nieustalone'] = [u for u in k['nieustalone'] if u['pole'] != 'ile.regula_kwoty']
        benefits.append(k)
        jednostki_karty = [z.get('id_jednostki') for z in karta['zrodla'] if z.get('id_jednostki')]
        article_refs = sorted({przepis_art_id(x.split('#')[0], x) for x in jednostki_karty} - {None})
        extra_karty[bid] = {'pochodzenie': 'reczna_FUS', 'zrodlo_id': karta['id'],
                            'rodzaj_zrodlowy': karta.get('rodzaj'), 'status_zrodlowy': karta.get('status'),
                            'artykuly': article_refs, 'jednostki': jednostki_karty,
                            'historia_parametr': przypisanie,
                            'uwaga_czasowa': karta.get('uwaga_czasowa'),
                            'odsylacze_do_sprawdzenia': karta.get('odeslania_do_sprawdzenia')}
    # Kandydaci automatyczni zachowują własne id i status weryfikacji; nigdy nie
    # są łączeni z opracowanymi kartami po samej podobnej nazwie.
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
            opis = (src.get('komu_krotko') or {}).get('tekst') or ''
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
            # Kwota tylko gdy jednoznaczny cytat o nazwie świadczenia i kwocie.
            stawki = [x for x in src.get('ile', []) if x.get('rodzaj') == 'kwota_w_ustawie' and x.get('tekst')]
            if len(stawki) == 1:
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
            if not k['ile']['aktualna']:
                k['nieustalone'].append(nieustalone('ile', 'Kwota nie została jednoznacznie potwierdzona w danych wejściowych.'))
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
                 'nieustalone_zrodla': src.get('nieustalone') or []}
    uzupelnij_notatkami(socjal, benefits, extra_karty, na_dzien)
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
    acts = []
    for eli in sorted(act_eli):
        m = akty_meta.get(eli, {})
        acts.append({'eli': eli, 'tytul': m.get('tytul') or 'Akt prawny {}'.format(eli),
          'typ': 'Ustawa' if eli in akty_meta else 'Akt prawny', 'data_stanu': m.get('stan'),
          'url_eli': eli_url(eli), 'url_isap': None, 'korzysci': sorted(set(akt_benefits[eli])),
          'wykonawcze': [], 'status': 'Stan prawny należy zweryfikować u źródła', 'pliki': []})
    slowniki = {'rodzaj_korzysci': {'swiadczenie_okresowe':'świadczenie okresowe',
            'swiadczenie_jednorazowe':'świadczenie jednorazowe','ulga_podatkowa':'ulga podatkowa',
            'zwolnienie':'zwolnienie','swiadczenie_rzeczowe':'świadczenie rzeczowe',
            'uprawnienie':'uprawnienie / mechanizm','dofinansowanie':'dofinansowanie'},
        'rodzaj_terminu': {'okres_kwoty':'okres obowiązywania kwoty','termin_wniosku':'termin złożenia wniosku',
            'granica_przepisu':'zmiana albo koniec przepisu','okres_zasilkowy':'okres przyznania prawa',
            'harmonogram_dostepnosci':'otwieranie prawa etapami','termin_wyplaty':'termin wypłaty'},
        'status': {'obowiazuje':'obowiązuje (według źródła)', 'zamknieta':'zamknięta',
                   'do_ustalenia':'do ustalenia'},
        'sytuacje': {'dziecko':'dziecko','ciaza_porod':'ciąża i poród',
           'niepelnosprawnosc':'niepełnosprawność','opieka_nad_bliskim':'opieka nad bliskim',
           'senior':'senior','niski_dochod':'niski dochód','utrata_pracy':'utrata pracy',
           'mieszkanie_energia':'mieszkanie i energia','edukacja':'edukacja', 'cudzoziemiec':'cudzoziemiec'}}
    extras = {'kontrakt': 'socjal-1', 'na_dzien': na_dzien,
              'karty': extra_karty, 'artykuly': sorted(artykuly.values(), key=lambda a: a['id']),
              'historia': historia,
              'statystyki': {'reczne': sum(v['pochodzenie']=='reczna_FUS' for v in extra_karty.values()),
                            'automatyczne': sum(v['pochodzenie']=='automat' for v in extra_karty.values()),
                            'z_notatek': sum(v['pochodzenie']=='notatka' for v in extra_karty.values())}}
    zapis(wynik / 'korzysci.json', benefits)
    zapis(wynik / 'akty.json', acts)
    zapis(wynik / 'slowniki.json', slowniki)
    zapis(wynik / 'socjal.json', extras)
    (wynik / 'akty').mkdir(parents=True, exist_ok=True)
    (wynik / 'akty/SHA256SUMS').write_text('', encoding='utf-8')
    manifest = {'kontrakt': KONTRAKT, 'wygenerowano': datetime.now(timezone.utc).isoformat(),
                'wersja_kodu': 'importuj_socjal-1.0', 'na_dzien': na_dzien,
                'pliki': {f: sha(wynik / f) for f in PODSTAWOWE},
                'zakres': sorted(akty_meta),
                'liczby': {'korzysci': len(benefits), 'akty': len(acts), 'pliki_aktow': 0},
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
