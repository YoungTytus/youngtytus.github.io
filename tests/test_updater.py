import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from argparse import Namespace
from unittest.mock import patch
import aktualizuj_strone as updater

from aktualizuj_strone import UpdateError, relative_file, validate_export
from scripts.github_pages import prefix_url, rewrite, check_output


class UpdaterTests(unittest.TestCase):
    def test_repository_name_with_dots_and_unsafe_base_paths(self):
        self.assertEqual(updater.normalize_base_path('/Mapa_soc.github.io/'), '/Mapa_soc.github.io')
        for path in ('/../sekret', '/.', '/x/../sekret', '//example.com'):
            with self.assertRaises(UpdateError):
                updater.normalize_base_path(path)

    def test_pages_prefix_preserves_external_urls_and_fragments(self):
        text = '<a href="/korzysci/?q=renta#x">x</a><a href="#x">x</a><a href="https://api.sejm.gov.pl/x">PDF</a>'
        output = rewrite(text, 'https://youngtytus.github.io', '/Mapa_soc.github.io')
        self.assertIn('href="/Mapa_soc.github.io/korzysci/?q=renta#x"', output)
        self.assertIn('href="#x"', output)
        self.assertIn('href="https://api.sejm.gov.pl/x"', output)
        self.assertEqual(rewrite(output, 'https://youngtytus.github.io', '/Mapa_soc.github.io'), output)

    def test_fonts_canonical_and_redirect(self):
        text = 'url(/_astro/font.woff2) <link href="https://youngtytus.github.io/korzysci/"><meta content="0;url=/korzysci/">'
        out = rewrite(text, 'https://youngtytus.github.io', '/Mapa_soc.github.io')
        self.assertIn('url(/Mapa_soc.github.io/_astro/font.woff2)', out)
        self.assertIn('https://youngtytus.github.io/Mapa_soc.github.io/korzysci/', out)
        self.assertIn('0;url=/Mapa_soc.github.io/korzysci/', out)

    def test_reject_parent_and_absolute_paths(self):
        for name in ('../secret', '/secret', 'C:/secret', 'akty\\bad.pdf'):
            with self.assertRaises(UpdateError):
                relative_file(Path('.'), name)

    def test_corrupted_export_is_rejected_before_import(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'manifest.json').write_text(json.dumps({'kontrakt':'strona-0.4', 'pliki':{'korzysci.json':'0'*64}}))
            (root / 'korzysci.json').write_text('[]')
            with self.assertRaisesRegex(UpdateError, 'SHA-256'):
                validate_export(root)

    def test_broken_project_url_is_detected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'index.html').write_text('<a href="/korzysci/">Błąd</a>', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'podścieżkę'):
                check_output(root, '/Mapa_soc.github.io')

    def test_failed_build_restores_previous_data_and_keeps_site(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old = root / 'data/eksport'
            source = root / 'nowy'
            for folder in (old, source):
                (folder / 'akty').mkdir(parents=True)
                for name in updater.FILES:
                    (folder / name).write_text('[]' if name == 'akty.json' else ('stare' if folder == old else 'nowe'))
            (root / 'dist').mkdir()
            (root / 'dist/index.html').write_text('poprzednia strona')
            (root / 'pages.json').write_text(json.dumps({'site_url':'https://youngtytus.github.io','base_path':'/Mapa_soc.github.io'}))
            args = Namespace(eksport=str(source), push=False, site_url=None, base_path=None, message=None)
            with patch.object(updater, 'ROOT', root), patch.object(updater, 'SNAPSHOT', old), \
                 patch.object(updater, 'validate_export', return_value={}), \
                 patch.object(updater, 'node_and_npm', return_value=('node',['npm'])), \
                 patch.object(updater, 'ensure_dependencies'), \
                 patch.object(updater, 'run', side_effect=UpdateError('błąd walidacji')):
                with self.assertRaises(UpdateError):
                    updater.update(args)
            self.assertEqual((old / 'korzysci.json').read_text(), 'stare')
            self.assertEqual((root / 'dist/index.html').read_text(), 'poprzednia strona')


if __name__ == '__main__':
    unittest.main()
