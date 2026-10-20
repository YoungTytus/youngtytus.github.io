"""Regresje importu sejfu Obsidian; kompatybilne z Pythonem 3.10.4."""
import json
from pathlib import Path
import tempfile
import unittest

from aktualizuj_strone import UpdateError, validate_export
from scripts.importuj_socjal import generuj


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


if __name__ == '__main__':
    unittest.main()
