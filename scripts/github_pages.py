"""Dostosowanie zbudowanego HTML do podścieżki GitHub Pages, Python 3.10.4."""
from __future__ import annotations
import argparse
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit


def prefix_url(value, base):
    if not base or not value.startswith('/') or value.startswith('//'):
        return value
    if value == base or value.startswith(base + '/') or value.startswith(base + '?') or value.startswith(base + '#'):
        return value
    return base + value


def rewrite(text, site_url, base):
    attr = re.compile(r'\b(href|src|action|poster)=("|\')(/[^"\']*)\2', re.I)
    text = attr.sub(lambda m: m[1] + '=' + m[2] + prefix_url(m[3], base) + m[2], text)
    text = re.sub(r'url\(((["\']?))(/[^)"\']*)\2\)',
                  lambda m: 'url(' + m[2] + prefix_url(m[3], base) + m[2] + ')', text)
    # Przekierowania statyczne Astro w meta refresh.
    text = re.sub(r'(url=)(/[^"\'<>\s]*)', lambda m: m[1] + prefix_url(m[2], base), text, flags=re.I)
    # Canonical, JSON-LD, sitemap i robots.txt używają tej samej domeny.
    origin = site_url.rstrip('/')
    text = re.sub(re.escape(origin) + r'(/[^\s"\'<>]*)',
                  lambda m: origin + prefix_url(m[1], base), text)
    return text


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        for name in ('href', 'src', 'action', 'poster'):
            if a.get(name):
                self.urls.append(a[name])


def check_output(folder, base):
    root = Path(folder).resolve()
    if not (root / 'index.html').is_file():
        raise ValueError('Brak index.html w głównym katalogu publikacji.')
    if list(root.rglob('*.pdf')):
        raise ValueError('Publikacja zawiera lokalne PDF-y; dozwolone są wyłącznie odnośniki.')
    if any(p.is_symlink() for p in root.rglob('*')):
        raise ValueError('Artefakt Pages nie może zawierać dowiązań.')
    count = 0
    for page in root.rglob('*.html'):
        parser = Links()
        parser.feed(page.read_text(encoding='utf-8'))
        for raw in parser.urls:
            url = urlsplit(unescape(raw))
            if url.scheme or url.netloc or not url.path:
                continue
            path = unquote(url.path)
            if path.startswith('/'):
                if base and not (path == base or path.startswith(base + '/')):
                    raise ValueError('Link omija podścieżkę Pages: ' + raw)
                path = path[len(base):] if base else path
                target = root / path.lstrip('/')
            else:
                target = page.parent / path
            if not target.resolve().is_relative_to(root):
                raise ValueError('Link wychodzi poza publikację: ' + raw)
            if not target.is_file() and not (target / 'index.html').is_file():
                raise ValueError('Martwy odnośnik: ' + str(page.relative_to(root)) + ' -> ' + raw)
            count += 1
    if sum(p.stat().st_size for p in root.rglob('*') if p.is_file()) >= 1024 ** 3:
        raise ValueError('Witryna przekracza limit rozmiaru 1 GB GitHub Pages.')
    return count


def finalize(folder, site_url, base):
    folder = Path(folder)
    for p in folder.rglob('*'):
        if p.is_file() and (p.suffix in ('.html', '.css', '.xml') or p.name == 'robots.txt'):
            text = p.read_text(encoding='utf-8')
            p.write_text(rewrite(text, site_url, base), encoding='utf-8')
    (folder / '.nojekyll').write_bytes(b'')
    count = check_output(folder, base)
    print('GitHub Pages: index.html, podścieżka, brak PDF i {} odnośników poprawne.'.format(count))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--site-url', required=True)
    parser.add_argument('--base-path', default='')
    args = parser.parse_args()
    finalize(args.folder, args.site_url, args.base_path.rstrip('/'))
