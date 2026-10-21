"""Regresje importu sejfu Obsidian; kompatybilne z Pythonem 3.10.4."""
import json
from pathlib import Path
import tempfile
import unittest

from aktualizuj_strone import UpdateError, validate_export
from scripts.importuj_socjal import (generuj, bez_kwoty, przenies_podsumowanie,
                                     przenies_terminy, nominalna_zastepowana, etykieta_wariantu,
                                     etykiety_serii, przenies_obliczona, przenies_limity)


class SocjalImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.socjal = self.base / 'Socjal'
        self.output = self.base / 'eksport'
        (self.socjal / 'Dane/FUS').mkdir(parents=True)
        (self.socjal / 'Swiadczenia/FUS').mkdir(parents=True)
        (self.socjal / 'Dane/FUS/karty.json').write_text(json.dumps([{
            'id': 'proba_testowa', 'nazwa': 'Próbne świadczenie',
            'rodzaj': 'swiadczenie_okresowe', 'komu': 'osobie wskazanej w przepisie',
            'regula_kwoty': 'Wysokość do ustalenia', 'zrodla': [{
                'id_jednostki': 'DU/1998/1118#arti_1',
                'przepis': 'art. 1', 'cytat': 'Przepis testowy.',
                'stan_pdf': '2026-10-20',
            }],
        }]), encoding='utf-8')
        (self.socjal / 'Dane/FUS/history_all_verified.json').write_text('[]', encoding='utf-8')

    def run_import(self):
        generuj(self.socjal, self.output, '2026-10-20')
        validate_export(self.output)
        korzysci = json.loads((self.output / 'korzysci.json').read_text(encoding='utf-8'))
        socjal = json.loads((self.output / 'socjal.json').read_text(encoding='utf-8'))
        return korzysci, socjal

    def test_base_and_immutable_source(self):
        before = (self.socjal / 'Dane/FUS/karty.json').read_bytes()
        k, extra = self.run_import()
        self.assertEqual(len(k), 1)
        self.assertEqual(k[0]['id'], 'FUS-proba-testowa')
        self.assertEqual(extra['karty'][k[0]['id']]['pochodzenie'], 'reczna_FUS')
        self.assertIsNone(k[0]['ile']['aktualna'])
        self.assertEqual(before, (self.socjal / 'Dane/FUS/karty.json').read_bytes())
        self.assertEqual(k[0]['ile']['regula']['opis'], 'Wysokość do ustalenia')

    def karta(self):
        return {'przepis': {'eli': 'DU/2004/593'}, 'ile': bez_kwoty(),
                'nieustalone': [], 'do_kiedy': []}

    def test_summary_keeps_limit_label_history_and_evidence(self):
        row = {'akt': 'DU/2024/1044', 'tekst': '1229 zł',
               'wariant': 'maksymalna kwota zasiłku stałego', 'od': '2025-01-01',
               'cytat': 'Maksymalna kwota zasiłku stałego: 1229 zł.',
               'sciezka': '§ 1', 'jednostka': 'DU/2024/1044#par_1',
               'sha256': 'a' * 64}
        src = {'akt': 'DU/2004/593', 'nazwa': 'zasiłek stały', 'ile_podsumowanie': {
            'rozwiazanie': 'kwota_z_aktu_wykonawczego', 'aktualna': [row],
            'historia': [row], 'trasa': [{'jednostka': row['jednostka'], 'opis': 'Kwota z rozporządzenia'}]}}
        k = self.karta()
        przenies_podsumowanie(src, k, {}, '2026-10-21')
        self.assertEqual(len(k['ile']['os_czasu']), 1)
        self.assertEqual(k['ile']['aktualna']['warianty'][0]['wartosc'], '1229 zł')
        self.assertIn('maksymalna', k['ile']['aktualna']['warianty'][0]['etykieta'])
        self.assertEqual(k['ile']['trasa'][0]['dowod']['_sha256'], 'a' * 64)
        k = self.karta()
        przenies_podsumowanie(src, k, {}, '2024-12-31')
        self.assertIsNone(k['ile']['aktualna'])

    def test_relative_deadlines_and_new_types_keep_meaning(self):
        src = {'do_kiedy': [{'rodzaj': typ, 'okres': '60 dni od otrzymania',
                'cytat': 'Dokument w terminie 60 dni od otrzymania.', 'sciezka': 'art. 106'}
                for typ in ['termin_dokumentu', 'termin_organu', 'termin_inny', 'wejscie_w_zycie']]}
        k = self.karta()
        przenies_terminy(src, k, {})
        self.assertEqual(len(k['do_kiedy']), 4)
        self.assertIsNone(k['do_kiedy'][0]['data'])
        self.assertEqual(k['do_kiedy'][0]['okres'], '60 dni od otrzymania')

    def test_nominal_amount_with_footnote_is_blocked(self):
        unit = {'przypisy': [{'tekst': 'Aktualną kwotę ogłasza Prezes ZUS.'}]}
        self.assertTrue(nominalna_zastepowana({'jednostka': 'u'}, {'u': unit}))

    def test_unrelated_price_from_application_form_is_rejected(self):
        row = {'akt': 'DU/2022/1712', 'tekst': '996,60 zł',
               'tytul_aktu': 'Rozporządzenie w sprawie wzoru wniosku',
               'cytat': 'Cena paliwa nie wyższa niż 996,60 zł.',
               'jednostka': 'DU/2022/1712#par_2', 'od': '2022-08-17'}
        src = {'akt': 'DU/2022/1692', 'nazwa': 'dodatek węglowy',
               'ile_podsumowanie': {'rozwiazanie': 'kwota_z_aktu_wykonawczego',
                'aktualna': [row], 'historia': [row],
                'trasa': [{'jednostka': row['jednostka']}]}}
        k = self.karta()
        self.assertFalse(przenies_podsumowanie(src, k, {}, '2026-10-21'))
        self.assertIsNone(k['ile']['aktualna'])
        self.assertEqual(k['ile']['os_czasu'], [])
        self.assertTrue(k['nieustalone'])

    def test_comparison_mode_deduplicates_only_matching_names(self):
        katalog = self.socjal / 'Dane/Mapa/DU-1998-1118'
        katalog.mkdir(parents=True)
        (katalog / 'przebieg.json').write_text(json.dumps({'akt': 'DU/1998/1118',
            'konfiguracja_aktu': {'tryb': 'porownanie'}}), encoding='utf-8')
        (katalog / 'jednostki.json').write_text('[]', encoding='utf-8')
        (katalog / 'korzysci.json').write_text(json.dumps({'korzysci': [
            {'id': 'auto-proba', 'nazwa': 'próbne świadczenie', 'akt': 'DU/1998/1118'},
            {'id': 'auto-inne', 'nazwa': 'inne świadczenie', 'akt': 'DU/1998/1118'}]}), encoding='utf-8')
        k, extra = self.run_import()
        self.assertEqual({x['id'] for x in k}, {'FUS-proba-testowa', 'auto-inne'})
        self.assertEqual(extra['pominiete_duplikaty'][0]['id'], 'auto-proba')

    def test_edited_markdown_changes_page_data(self):
        note = self.socjal / 'Swiadczenia/FUS/proba.md'
        note.write_text('---\ntyp: "karta_korzysci"\nidentyfikator: "proba_testowa"\nustawa: "DU/1998/1118"\n---\n# Próbne świadczenie\n\n## Komu przysługuje\n\nJedna osoba.\n\n## Ile wynosi\n\nKwota zależna od warunków.\n', encoding='utf-8')
        k, extra = self.run_import()
        self.assertEqual(k[0]['komu'], 'Jedna osoba.')
        self.assertIn('Kwota zależna', extra['karty'][k[0]['id']]['opis_kwoty_z_notatki'])
        self.assertIsNone(k[0]['ile']['aktualna'])
        note.write_text(note.read_text(encoding='utf-8').replace('Jedna osoba.', 'Dwie osoby.'), encoding='utf-8')
        k, _ = self.run_import()
        self.assertEqual(k[0]['komu'], 'Dwie osoby.')

    def test_new_markdown_card_is_unverified_and_published(self):
        note = self.socjal / 'Swiadczenia/FUS/nowa.md'
        note.write_text('---\ntyp: "karta_korzysci"\nidentyfikator: "nowy_dodatek"\nustawa: "DU/1998/1118"\n---\n# Nowy dodatek\n\n## Komu przysługuje\n\nTestowa grupa.\n', encoding='utf-8')
        k, extra = self.run_import()
        nowa = next(b for b in k if b['id'] == 'SOCJAL-nowy-dodatek')
        self.assertEqual(nowa['status'], 'do_ustalenia')
        self.assertIsNone(nowa['ile']['aktualna'])
        self.assertEqual(extra['statystyki']['z_notatek'], 1)

    def test_protected_sidecar_detects_tampering(self):
        self.run_import()
        with (self.output / 'socjal.json').open('a', encoding='utf-8') as f:
            f.write(' ')
        with self.assertRaisesRegex(UpdateError, 'SHA-256'):
            validate_export(self.output)

    def test_parallel_amounts_from_one_act_become_variants(self):
        def row(kw, wariant, naglowek):
            return {'akt': 'MP/2026/220', 'tekst': kw, 'wariant': wariant, 'naglowek_punktu': naglowek,
                    'od': '2026-03-01', 'cytat': kw + ' – ' + wariant, 'jednostka': 'MP/2026/220#tresc'}
        rows = [row('1978,49 zł', 'a) miesięcznie – emerytura, renta rodzinna i renta dla osób całkowicie niezdolnych do pracy',
                    'kwoty najniższej emerytury i renty wynoszą'),
                row('1483,87 zł', 'miesięcznie – renta dla osób częściowo niezdolnych do pracy',
                    'kwoty najniższej emerytury i renty wynoszą')]
        src = {'akt': 'DU/1998/1118', 'nazwa': 'renta', 'ile_podsumowanie': {
            'rozwiazanie': 'kwota_z_aktu_wykonawczego', 'aktualna': rows, 'historia': rows, 'trasa': []}}
        k = self.karta()
        przenies_podsumowanie(src, k, {}, '2026-10-21')
        self.assertEqual(len(k['ile']['os_czasu']), 1)
        warianty = k['ile']['aktualna']['warianty']
        self.assertEqual([w['wartosc'] for w in warianty], ['1978,49 zł', '1483,87 zł'])
        self.assertEqual(warianty[0]['etykieta'],
                         'najniższa: emerytura, renta rodzinna i renta dla osób całkowicie niezdolnych do pracy')
        self.assertNotIn('nieustalone', [n['pole'] for n in k['nieustalone']])

    def test_second_manual_package_sw_format(self):
        (self.socjal / 'Dane/SW').mkdir(parents=True)
        zrodlo = {'akt': 'DU/2016/195', 'typ': 'U', 'sha256': 'b' * 64, 'strona': 8, 'przepis': 'art. 5 ust. 1',
                  'cytat': 'Świadczenie wychowawcze przysługuje … w wysokości 800,00 zł miesięcznie na dziecko.'}
        (self.socjal / 'Dane/SW/core_cards.json').write_text(json.dumps([
            {'id': 'wychowawcze', 'nazwa': 'Świadczenie wychowawcze 500 i 800 plus', 'rodzaj': 'swiadczenie_glowne',
             'komu': 'rodzic', 'regula_kwoty': '800 zł', 'zrodla': [zrodlo]},
            {'id': 'koszty_gmina_historyczne', 'nazwa': 'Koszty gmin', 'rodzaj': 'historyczny_transfer_instytucjonalny',
             'komu': 'gmina', 'regula_kwoty': '2 %', 'zrodla': [zrodlo]}]), encoding='utf-8')
        historia = [{'parametr': 'swiadczenie_wychowawcze_kwota_pelna', 'od': od, 'do': do, 'kwota': kw,
                     'status_wartosci': 'potwierdzone_z_aktu', 'source': dict(zrodlo, cytat=zrodlo['cytat'])}
                    for od, do, kw in [('2016-04-01', '2023-12-31', '500.00'), ('2024-01-01', None, '800.00')]]
        (self.socjal / 'Dane/SW/history_verified.json').write_text(json.dumps(historia), encoding='utf-8')
        katalog = self.socjal / 'Dane/Mapa/DU-2016-195'
        katalog.mkdir(parents=True)
        (katalog / 'przebieg.json').write_text(json.dumps({'akt': 'DU/2016/195',
            'konfiguracja_aktu': {'tryb': 'porownanie'}}), encoding='utf-8')
        (katalog / 'jednostki.json').write_text('[]', encoding='utf-8')
        (katalog / 'korzysci.json').write_text(json.dumps({'korzysci': [
            {'id': 'DU-2016-195-swiadczenie-wychowawcze', 'nazwa': 'świadczenie wychowawcze', 'akt': 'DU/2016/195'},
            {'id': 'DU-2016-195-opieka', 'nazwa': 'opieka', 'akt': 'DU/2016/195'}]}), encoding='utf-8')
        k, extra = self.run_import()
        karty = {x['id']: x for x in k}
        self.assertEqual(karty['SW-wychowawcze']['ile']['aktualna']['wartosc'], '800,00 zł')
        self.assertEqual([w['wartosc'] for w in karty['SW-wychowawcze']['ile']['os_czasu']], ['500,00 zł', '800,00 zł'])
        self.assertEqual(karty['SW-koszty-gmina-historyczne']['status'], 'zamknieta')
        self.assertEqual(karty['SW-koszty-gmina-historyczne']['rodzaj_korzysci'], 'dofinansowanie')
        self.assertNotIn('DU-2016-195-swiadczenie-wychowawcze', karty)   # alias → karta ręczna
        self.assertNotIn('DU-2016-195-opieka', karty)                    # szum słownika pominięty z powodem
        self.assertEqual(extra['karty']['SW-wychowawcze']['pochodzenie'], 'reczna_SW')

    def test_one_label_per_series_across_years(self):
        stary = {'akt': 'MP/2016/1', 'tekst': '676,75 zł', 'wariant_klucz': 'rent czes', 'od': '2016-03-01',
                 'do': '2017-02-28', 'wariant': '— dla rent z tytułu częściowej niezdolno- ści', 'cytat': 'x',
                 'jednostka': 'MP/2016/1#tresc'}
        nowy = {'akt': 'MP/2026/220', 'tekst': '1483,87 zł', 'wariant_klucz': 'rent czes', 'od': '2026-03-01',
                'wariant': 'miesięcznie – renta dla osób częściowo niezdolnych do pracy',
                'naglowek_punktu': 'kwoty najniższej emerytury i renty wynoszą', 'cytat': 'y',
                'jednostka': 'MP/2026/220#tresc'}
        rozlany = dict(stary, od='1999-06-01', do='2000-05-31', wariant_klucz='rent czes rent rodz',
                       wariant='renta dla osoby częściowo niezdolnej, renta rodzinna. 2')
        etykiety, klucz = etykiety_serii([rozlany, stary, nowy], 'renta')
        self.assertEqual(etykiety, {'rent czes': 'najniższa: renta dla osób częściowo niezdolnych do pracy'})
        self.assertEqual(klucz(rozlany), 'rent czes')

    def test_variant_label_drops_announcement_preamble_and_bare_name(self):
        self.assertEqual(etykieta_wariantu('U. z 2023 r. poz. 2194) ogłasza się, że od dnia 1 marca 2026 r. kwota dodatku'),
                         'kwota dodatku')
        self.assertEqual(etykieta_wariantu('a) miesięcznie – emerytura'), 'emerytura')
        etykiety, _ = etykiety_serii([{'wariant': 'ogłasza się, że od dnia 1 marca 2026 r. kwota dodatku dopełniającego'}],
                                     'dodatek dopełniający')
        self.assertEqual(list(etykiety.values()), [None])
        etykiety, _ = etykiety_serii([{'wariant': 'maksymalną kwotę zasiłku stałego'}], 'zasiłek stały')
        self.assertIn('maksymalną', list(etykiety.values())[0])

    def test_calculated_amount_and_limit_have_evidence(self):
        wielkosci = {'najnizsza': {'nazwa': 'kwota najniższej renty', 'seria': [
            {'akt': 'MP/2026/220', 'od': '2026-03-01', 'tekst': '1978,49 zł', 'cytat': 'a) 1978,49 zł miesięcznie – renta'}]},
            'kryterium': {'nazwa': 'kryterium', 'seria': [
            {'akt': 'DU/2021/1296', 'od': '2022-01-01', 'do': '2024-12-31', 'tekst': '600 zł', 'cytat': 'b) 600 zł'},
            {'akt': 'DU/2024/1044', 'od': '2025-01-01', 'tekst': '823 zł', 'cytat': 'b) 823 zł'}]}}
        src = {'akt': 'DU/2003/1268', 'nazwa': 'renta socjalna', 'ile_podsumowanie': {'obliczona': [{
            'wynik': '1978.49', 'procent': '100.0', 'wielkosc': 'najnizsza', 'regula': '100 % kwoty najniższej renty',
            'historia': [{'od': '2026-03-01', 'do': None, 'podstawa': '1978.49', 'wynik': '1978.49', 'akt': 'MP/2026/220'}]}]}}
        k = self.karta()
        self.assertTrue(przenies_obliczona(src, k, {}, wielkosci, '2026-10-21'))
        self.assertEqual(k['ile']['wyliczenie']['wartosc'], '1978,49 zł')
        self.assertEqual(k['ile']['regula']['udzial'], '100 %')
        self.assertEqual(k['ile']['wyliczenie']['podstawa']['dowod']['eli'], 'MP/2026/220')
        src = {'ile_podsumowanie': {'limity': [{'rodzaj': 'maksimum', 'wielkosc': 'kryterium', 'sciezka': 'art. 38 ust. 2 pkt 1',
                                                'cytat': 'nie może być wyższa niż kwota kryterium dochodowego'}]}}
        k = self.karta()
        przenies_limity(src, k, wielkosci)
        wpisy = k['ile']['progi'][0]['wpisy']
        self.assertEqual([w['wartosc'] for w in wpisy], ['600 zł', '823 zł'])
        self.assertEqual(wpisy[-1]['_rodzaj'], 'maksimum')
        k = self.karta()
        src['ile_podsumowanie']['limity'][0]['cytat'] = 'nie może być niższa niż 10 % kwoty kryterium'
        przenies_limity(src, k, wielkosci)
        self.assertEqual(k['ile']['progi'], [])


if __name__ == '__main__':
    unittest.main()
