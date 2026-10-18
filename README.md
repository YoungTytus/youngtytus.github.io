# Mapa Polskiego Socjalu — aktualizacja bez kredytów AI

Projekt zachowuje szatę graficzną strony przygotowanej w Astro. Skrypt
`aktualizuj_strone.py`, zgodny z **Pythonem 3.10.4**, importuje eksport, sprawdza
sumy SHA-256, uruchamia testy, tworzy kompletną witrynę i opcjonalnie wykonuje
commit oraz push do `YoungTytus/youngtytus.github.io`. Nie korzysta z API AI ani Sites.

Python obsługuje proces; HTML i CSS generuje dołączony projekt Astro. Potrzebne
są **Python 3.10.4, Node.js 22 lub nowszy wraz z npm oraz Git**. Nie trzeba
instalować żadnych bibliotek przez pip. Zależności Node są instalowane
automatycznie z `package-lock.json`, kiedy są potrzebne.

## Pierwsze uruchomienie

Otwórz terminal w wybranym folderze i pobierz projekt:

```powershell
git clone https://github.com/YoungTytus/youngtytus.github.io.git
cd youngtytus.github.io
py -3.10 aktualizuj_strone.py --eksport "C:\Users\Kamil\Documents\Fundacja\Fundacja\eksport"
```

To buduje stronę lokalnie, bez wysyłania zmian. Gotowy wynik znajduje się w
`dist/`. Aby obejrzeć stronę, przygotuj folder podglądu (podścieżka jest taka
sama jak na GitHubie):

```powershell
python -m http.server 8000 --directory dist
```

Otwórz `http://localhost:8000/`. Samo otwarcie `index.html` dwuklikiem
nie zastępuje serwera, ponieważ strona używa ścieżek od katalogu witryny.

## Każda kolejna aktualizacja

Wygeneruj nowy eksport w systemie źródłowym i uruchom:

```powershell
py -3.10 aktualizuj_strone.py --eksport "C:\Users\Kamil\Documents\Fundacja\Fundacja\eksport" --push
```

Skrypt wykonuje wszystkie kroki. Po pushu workflow GitHub Actions ponownie
sprawdza projekt i publikuje wynik w GitHub Pages. Jeśli sam edytowałeś
wygląd w `src/`, ta sama komenda dołącza zmiany kodu strony do commita.

Bez `--eksport` używany jest ostatni zaimportowany snapshot w `data/eksport/`.
Bez `--push` nie jest wykonywany commit ani wysyłanie do GitHuba.
Alias `--exkort` działa tak samo jak `--eksport`.

Git używa zwykłego lokalnego logowania (np. Git Credential Manager). Skrypt
nie zawiera tokena i nie zapisuje danych logowania. Przy pierwszym pushu Git
może poprosić o zalogowanie. Jeżeli Git nie ma ustawionego autora, ustaw własne
`git config user.name` oraz `git config user.email`.

Skrypt nie wykonuje `force push`, nie zmienia repozytorium zdalnego i odmawia
wysyłania, jeśli `origin` wskazuje inne repo lub pracujesz poza `main`.
Gdy na GitHubie są nowsze zmiany, najpierw wykonaj `git pull --ff-only`.
W razie rozbieżności rozwiąż konflikt normalnie w Git; skrypt go nie nadpisze.
Jeśli build lub kontrola danych nie przejdą, dotychczasowy `dist/` pozostaje
na miejscu, dane są przywracane, a push nie jest wykonywany.

## Jednorazowe włączenie GitHub Pages

W repozytorium wybierz **Settings → Pages → Build and deployment → Source →
GitHub Actions**. Następnie uruchom workflow z zakładki Actions lub wyślij zmianę.
Oczekiwany adres po poprawnej publikacji:

`https://youngtytus.github.io/`

Repozytorium i strona są publiczne. Publikacja jest obsługiwana przez GitHub Actions; kolejne aktualizacje nie wymagają edytora Sites. GitHub Actions i Pages mają własne limity zasobów.

Workflow `.github/workflows/pages.yml` ma `contents: read`, a job publikacji
`pages: write` i `id-token: write`, środowisko `github-pages` i zależność
od udanego buildu. PR uruchamia kontrolę i budowanie, lecz nie publikuje.
Artefakt zawiera `index.html` w katalogu głównym, `.nojekyll`, brak dowiązań
i ma kontrolowany limit 1 GB. Foldery `node_modules/` i `dist/` nie trafiają
do repozytorium.

Strona pod adresem `chatgpt.site` jest osobnym wdrożeniem. Wysłanie tego
repozytorium jej nie aktualizuje. Po przejściu na Pages używaj nowego adresu
lub podłącz własną domenę w ustawieniach GitHuba.

## Dane i dokumenty

Obsługiwane są znane formaty `strona-0.1`–`strona-0.4`. Nowa, nieznana wersja
kontraktu zatrzyma import, zamiast ignorować zmianę formatu. Import zachowuje
oryginalne bajty JSON i nie przelicza kwot, reguł procentowych ani dat prawnych.
Nowe strony powstają automatycznie z rekordów. Nazwy, statusy, cytaty i kategorie
pochodzą z eksportu; przypisania automatyczne są tak oznaczone na stronie.

Do snapshotu trafiają cztery pliki JSON, `akty/SHA256SUMS` i ewentualne
naprawione teksty TXT. **PDF-y nie są kopiowane do repozytorium ani witryny**.
Jeśli eksport zawiera PDF-y, skrypt sprawdza ich sumy i rozmiary przed importem.
Pobieranie na stronie prowadzi bezpośrednio do adresów API Sejmu podanych
w danych. Gdy adresu PDF nie ma, pozostaje odnośnik do karty aktu w API;
skrypt nie zgaduje nazwy pliku. Naprawione TXT są publikowane jako oznaczone
pliki pochodne do kopiowania tekstu; ich sumy także są sprawdzane.

Progi dochodowe, warianty reguł, etapy dostępności i warunkowe zwiększenia
kwoty są pokazywane oddzielnie. Zwiększenia nie są sumowane z kwotą główną.
Walidacja techniczna nie jest audytem merytorycznym eksportu.

## Własna domena lub inny adres

Zmień `pages.json`, np. ustaw `site_url` na swoją domenę HTTPS i `base_path`
na pusty napis, a potem przebuduj i wyślij projekt. Parametry `--site-url`
i `--base-path` służą do lokalnych prób; dla publikacji automatycznej zapisz
ustawienia w `pages.json`. Konfigurację DNS i domenę w Pages ustaw osobno.

## Dokumentacja źródłowa

- [Tworzenie witryny GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site)
- [Publikowanie przez GitHub Actions](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)
- [Limity GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits)
- [Astro na GitHub Pages](https://docs.astro.build/en/guides/deploy/github/)
