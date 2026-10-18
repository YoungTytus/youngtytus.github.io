#!/usr/bin/env python3
"""Python 3.10.4: eksport -> Astro -> statyczna witryna -> opcjonalny git push.

Bez pakietów pip, API AI, tokenów w kodzie i pobierania PDF-ów.
Wymaga Node.js 22+ i Git (tylko do --push).
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
SNAPSHOT = ROOT / 'data' / 'eksport'
REPO = 'https://github.com/YoungTytus/youngtytus.github.io.git'
FILES = ('manifest.json', 'korzysci.json', 'akty.json', 'slowniki.json', 'akty/SHA256SUMS')
MANAGED = ('src', 'public', 'schema', 'scripts', 'testy', 'data', 'tests', '.github',
           'astro.config.mjs', 'package.json', 'package-lock.json', 'tsconfig.json',
           'aktualizuj_strone.py', 'README.md', 'pages.json', '.gitignore', '.gitattributes')


class UpdateError(Exception):
    pass


def run(args, *, env=None, capture=False):
    """Argumenty jako lista; bez shell=True i bez sekretów w argumentach."""
    result = subprocess.run([str(x) for x in args], cwd=ROOT, env=env,
                            text=True, encoding='utf-8', errors='replace',
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE if capture else None)
    if result.returncode:
        detail = (result.stderr or result.stdout or '').strip() if capture else ''
        raise UpdateError('Polecenie zakończyło się błędem: ' + str(args[0]) +
                          ('\n' + detail if detail else ''))
    return result.stdout.strip() if capture else ''


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def relative_file(root, name):
    p = PurePosixPath(name)
    if not name or '\\' in name or p.is_absolute() or '..' in p.parts or ':' in name:
        raise UpdateError('Niebezpieczna ścieżka w eksporcie: ' + name)
    root = Path(root).resolve()
    candidate = root.joinpath(*p.parts)
    if not candidate.resolve().is_relative_to(root):
        raise UpdateError('Plik wychodzi poza folder eksportu: ' + name)
    if candidate.is_symlink():
        raise UpdateError('Dowiązanie zamiast pliku eksportu: ' + name)
    return candidate


def load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as exc:
        raise UpdateError('Nie można odczytać JSON: ' + str(path)) from exc


def normalize_base_path(value):
    value = value.rstrip('/')
    if value and (not re.fullmatch(r'/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*', value)
                  or any(part in ('.', '..') for part in value.split('/')[1:])):
        raise UpdateError('Niepoprawny --base-path.')
    return value


def validate_export(source):
    """Sumy oryginalnych bajtów. Nie zmienia manifestu ani danych prawnych."""
    source = Path(source).resolve()
    manifest = load_json(source / 'manifest.json')
    if manifest.get('kontrakt') not in ('strona-0.1', 'strona-0.2', 'strona-0.3', 'strona-0.4'):
        raise UpdateError('Nieobsługiwany kontrakt: ' + str(manifest.get('kontrakt')))
    hashes = manifest.get('pliki', {})
    for name in FILES[1:]:
        expected = hashes.get(name)
        path = relative_file(source, name)
        if not isinstance(expected, str) or not re.fullmatch('[a-f0-9]{64}', expected):
            raise UpdateError('Brak poprawnej sumy SHA-256 w manifeście: ' + name)
        if not path.is_file() or digest(path) != expected:
            raise UpdateError('Niezgodna suma SHA-256 lub brak pliku: ' + name)
    benefits, acts = load_json(source / 'korzysci.json'), load_json(source / 'akty.json')
    if not isinstance(benefits, list) or not isinstance(acts, list) or not benefits:
        raise UpdateError('Eksport nie zawiera prawidłowych list rekordów.')
    sums = {}
    for line in (source / 'akty/SHA256SUMS').read_text(encoding='utf-8-sig').splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r'([a-f0-9]{64}) [ *](.+)', line)
        if not match:
            raise UpdateError('Nieprawidłowy wiersz akty/SHA256SUMS.')
        key = match[2].removeprefix('./').removeprefix('akty/')
        relative_file(source / 'akty', key)
        if key in sums and sums[key] != match[1]:
            raise UpdateError('Powtórzona, sprzeczna suma pliku: ' + key)
        sums[key] = match[1]
    verified = 0
    for act in acts:
        for doc in act.get('pliki', []):
            name = doc['plik']
            path = relative_file(source, name)
            if sums.get(name.removeprefix('akty/')) != doc['sha256']:
                raise UpdateError('SHA256SUMS różni się od akty.json: ' + name)
            url = doc.get('url_zrodla')
            if url is not None and not re.match(r'^https://api\.sejm\.gov\.pl/eli/acts/', url):
                raise UpdateError('Niepoprawny adres PDF w API Sejmu: ' + name)
            # Dostarczone PDF-y sprawdzamy, lecz nigdy ich nie kopiujemy.
            if path.is_file():
                if digest(path) != doc['sha256'] or path.stat().st_size != doc['rozmiar']:
                    raise UpdateError('Niezgodny PDF: ' + name)
                verified += 1
            elif source != SNAPSHOT.resolve() and manifest.get('z_plikami_pdf'):
                raise UpdateError('Manifest deklaruje PDF, ale brakuje pliku: ' + name)
            repaired = doc.get('tekst_naprawiony')
            if repaired:
                text = relative_file(source, repaired['plik'])
                if not text.is_file() or digest(text) != repaired['sha256'] or text.stat().st_size != repaired['rozmiar']:
                    raise UpdateError('Niezgodny naprawiony tekst: ' + repaired['plik'])
    counts = manifest.get('liczby', {})
    actual = {'korzysci': len(benefits), 'akty': len(acts),
              'pliki_aktow': sum(len(a.get('pliki', [])) for a in acts)}
    for key, value in actual.items():
        if key in counts and counts[key] != value:
            raise UpdateError('Liczba rekordów nie zgadza się z manifestem: ' + key)
    print('Eksport: {} korzyści, {} aktów; zweryfikowane dostarczone PDF: {}.'.format(
        len(benefits), len(acts), verified))
    return manifest


def node_and_npm():
    node = shutil.which('node')
    if not node:
        raise UpdateError('Zainstaluj Node.js 22 lub nowszy i ponownie otwórz terminal.')
    if int(run([node, '--version'], capture=True).lstrip('v').split('.')[0]) < 22:
        raise UpdateError('Wymagany jest Node.js 22 lub nowszy.')
    npm = shutil.which('npm')
    candidates = [Path(node).parent / 'node_modules/npm/bin/npm-cli.js']
    if npm:
        candidates += [Path(npm).resolve().parent / 'node_modules/npm/bin/npm-cli.js',
                       Path(npm).resolve().parent.parent / 'lib/node_modules/npm/bin/npm-cli.js']
    cli = next((p for p in candidates if p.is_file()), None)
    if cli:
        return node, [node, str(cli)]
    if npm and os.name != 'nt':
        return node, [npm]
    raise UpdateError('Nie znaleziono npm. Zainstaluj oficjalny pakiet Node.js razem z npm.')


def ensure_dependencies(node, npm, env):
    stamp = ROOT / '.cache/dependencies.sha256'
    expected = digest(ROOT / 'package-lock.json')
    if (ROOT / 'node_modules/astro/astro.js').is_file() and stamp.is_file() and stamp.read_text().strip() == expected:
        return
    print('Instaluję zależności projektu z package-lock.json (npm ci).')
    run(npm + ['ci', '--no-audit', '--no-fund'], env=env)
    stamp.parent.mkdir(exist_ok=True)
    stamp.write_text(expected, encoding='ascii')


def git_preflight():
    if not shutil.which('git') or not (ROOT / '.git').exists():
        raise UpdateError('Do wysyłania zmian użyj klonu repozytorium: git clone ' + REPO)
    remote = run(['git', 'remote', 'get-url', 'origin'], capture=True)
    normalized = remote.removesuffix('.git').rstrip('/').lower()
    if normalized not in ('https://github.com/youngtytus/youngtytus.github.io', 'git@github.com:youngtytus/youngtytus.github.io'):
        raise UpdateError('Origin nie wskazuje na YoungTytus/youngtytus.github.io. Nie zmieniam zdalnego repozytorium.')
    if run(['git', 'branch', '--show-current'], capture=True) != 'main':
        raise UpdateError('Przełącz repozytorium na gałąź main przed --push.')
    for field in ('user.name', 'user.email'):
        if not run(['git', 'config', '--get', field], capture=True):
            raise UpdateError('Ustaw Git ' + field + ' przed wysłaniem zmian.')
    staged = run(['git', 'diff', '--cached', '--name-only'], capture=True).splitlines()
    if any(not any(p == m or p.startswith(m + '/') for m in MANAGED) for p in staged):
        raise UpdateError('Indeks Git zawiera inne pliki. Zatwierdź lub wycofaj ich przygotowanie osobno.')
    run(['git', 'fetch', 'origin'])
    exists = subprocess.run(['git', 'show-ref', '--verify', '--quiet', 'refs/remotes/origin/main'], cwd=ROOT).returncode == 0
    if exists:
        ancestor = subprocess.run(['git', 'merge-base', '--is-ancestor', 'origin/main', 'HEAD'], cwd=ROOT).returncode
        if ancestor:
            raise UpdateError('GitHub zawiera nowsze lub rozbieżne zmiany. Wykonaj git pull --ff-only i spróbuj ponownie.')


def push_changes(message):
    paths = [p for p in MANAGED if (ROOT / p).exists()]
    run(['git', 'add', '--'] + paths)
    changed = subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=ROOT).returncode
    if changed == 1:
        run(['git', 'commit', '-m', message])
    elif changed != 0:
        raise UpdateError('Nie udało się sprawdzić indeksu Git.')
    else:
        print('Brak nowych zmian do zatwierdzenia.')
    run(['git', 'push', '-u', 'origin', 'HEAD:main'])
    print('Zmiany wysłane. Stan publikacji: https://github.com/YoungTytus/youngtytus.github.io/actions')


def update(args):
    if not SNAPSHOT.resolve().is_relative_to(ROOT.resolve()) or SNAPSHOT.is_symlink():
        raise UpdateError('Folder danych projektu nie może prowadzić poza projekt.')
    config = load_json(ROOT / 'pages.json')
    site_url = args.site_url or config['site_url']
    base_path = args.base_path if args.base_path is not None else config['base_path']
    parsed = urlsplit(site_url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.path not in ('', '/') or parsed.query or parsed.fragment or parsed.username:
        raise UpdateError('--site-url powinien być samym adresem HTTPS bez ścieżki, np. https://youngtytus.github.io')
    base_path = normalize_base_path(base_path)
    source = Path(args.eksport).expanduser().resolve() if args.eksport else SNAPSHOT
    manifest = validate_export(source)
    if args.push:
        git_preflight()
    node, npm = node_and_npm()
    env = dict(os.environ, ASTRO_TELEMETRY_DISABLED='1', SITE_URL=site_url.rstrip('/'), SITE_BASE=base_path,
               PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    env.pop('EKSPORT', None)
    env.pop('PRZYKLAD', None)
    env.pop('SPRAWDZ_SUMY', None)
    ensure_dependencies(node, npm, env)
    work = ROOT / '.work'
    work.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='aktualizacja-', dir=work) as temporary:
        temp = Path(temporary)
        previous = temp / 'poprzedni-eksport'
        imported = source != SNAPSHOT.resolve()
        if imported:
            if SNAPSHOT.exists():
                shutil.copytree(SNAPSHOT, previous)
            repaired_files = [d['tekst_naprawiony']['plik'] for a in load_json(source / 'akty.json')
                              for d in a.get('pliki', []) if d.get('tekst_naprawiony')]
            # Usuń stare metadane/TXT tylko z własnego, stałego snapshotu.
            if SNAPSHOT.exists():
                shutil.rmtree(SNAPSHOT)
            try:
                for name in list(FILES) + repaired_files:
                    target = relative_file(SNAPSHOT, name)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(relative_file(source, name), target)
            except BaseException:
                if SNAPSHOT.exists():
                    shutil.rmtree(SNAPSHOT)
                if previous.exists():
                    shutil.copytree(previous, SNAPSHOT)
                raise
        try:
            # Oryginalny schemat i testy generatora uruchamiamy przed publikowaniem.
            run([node, 'scripts/waliduj.mjs'], env=env)
            run([node, '--test'] + sorted(str(p.relative_to(ROOT)) for p in (ROOT / 'testy').glob('*.test.mjs')), env=env)
            run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'], env=env)
            output = temp / 'dist'
            run([node, 'node_modules/astro/astro.js', 'build', '--outDir', output], env=env)
            run([node, 'scripts/sprawdz-html.mjs', output], env=env)
            run([sys.executable, 'scripts/github_pages.py', output, '--site-url', site_url, '--base-path', base_path], env=env)
            previous_site = temp / 'poprzednia-strona'
            if (ROOT / 'dist').exists():
                (ROOT / 'dist').rename(previous_site)
            try:
                output.rename(ROOT / 'dist')
            except BaseException:
                if previous_site.exists():
                    previous_site.rename(ROOT / 'dist')
                raise
        except BaseException:
            if imported:
                if SNAPSHOT.exists():
                    shutil.rmtree(SNAPSHOT)
                if previous.exists():
                    shutil.copytree(previous, SNAPSHOT)
            raise
    print('Gotowa strona: ' + str(ROOT / 'dist'))
    if args.push:
        push_changes(args.message or 'Aktualizacja danych ' + str(manifest.get('wygenerowano', datetime.now().isoformat())))
    else:
        print('Tryb lokalny: niczego nie wysłano. Dodaj --push, aby zaktualizować GitHub.')


def main():
    if sys.version_info < (3, 10):
        raise SystemExit('Wymagany Python 3.10.4 lub nowszy.')
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--eksport', '--exkort', help='Folder eksportu; domyślnie data/eksport w projekcie.')
    parser.add_argument('--push', action='store_true', help='Po poprawnym zbudowaniu wykonaj commit i git push do main.')
    parser.add_argument('--message', help='Własny opis commita.')
    parser.add_argument('--site-url', help='Adres serwera HTTPS, bez podścieżki.')
    parser.add_argument('--base-path', help='Podścieżka witryny, domyślnie pusty (witryna konta).')
    try:
        update(parser.parse_args())
    except (UpdateError, OSError, ValueError, KeyError) as exc:
        parser.exit(1, 'BŁĄD: ' + str(exc) + '\nAktualizacja przerwana. Sprawdź komunikat i stan zmian w Git.\n')


if __name__ == '__main__':
    main()
