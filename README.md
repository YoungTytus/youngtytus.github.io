# Mapa Polskiego Socjalu: witryna Astro + projekt Socjal

**Wersja importera: 1.3** (zmiany: `ZMIANY-M20.md` dla 1.1, `ZMIANY-1.2.md` dla 1.2, `ZMIANY-1.3.md` dla 1.3 — świadczenie wychowawcze). Wygląd działającej witryny Astro zostaje zachowany. Dane pochodzą z osobnego projektu `Socjal` w formacie Obsidiana i JSON. Witryna nie wymaga bazy danych ani serwera aplikacyjnego. Python odczytuje dane, normalizuje powiązania i tworzy paczkę dla Astro, a Astro generuje strony statyczne.

Do pracy wymagane są **Python 3.10.4**, **Node.js 22** (z npm) i opcjonalnie Git do publikacji. Importer nie wymaga dodatkowych bibliotek Pythona.

## 1. Gdzie umieścić foldery

Przykładowo:

```text
C:\Users\Kamil\Documents\Fundacja\
├── Socjal\                 # źródłowy projekt Obsidian, bez zmian
│   ├── START.md
│   ├── Swiadczenia\
│   ├── Dane\
│   │   ├── FUS\
│   │   └── Mapa\
│   ├── Mapa\
│   ├── Mapowanie\
│   └── Załączniki\
└── youngtytus.github.io\   # repozytorium strony, z nowymi plikami z tej paczki
    ├── aktualizuj_strone.py
    ├── scripts\importuj_socjal.py
    ├── src\
    └── data\eksport\
```

**Ważne:** dostarczone archiwum kodu nie zawiera folderu `.git`. Nie kasuj własnego klonu Git. Skopiuj pliki z tego archiwum do istniejącego folderu repozytorium `youngtytus.github.io`, nadpisując pliki o tych samych nazwach. Nie kopiuj źródłowego projektu `Socjal` do publicznego repozytorium strony.

## 2. Odtwórz stronę z obecnego projektu Socjal

W PowerShellu przejdź do repozytorium:

```powershell
cd "C:\Users\Kamil\Documents\Fundacja\youngtytus.github.io"
py -3.10 aktualizuj_strone.py --socjal "C:\Users\Kamil\Documents\Fundacja\Socjal"
```

Skrypt:

1. odczytuje karty z `Dane/FUS/karty.json`, zweryfikowaną historię z `Dane/FUS/history_all_verified.json`, mapowania `Dane/Mapa/DU-*/jednostki.json` oraz `korzysci.json` i notatki `Swiadczenia/**/*.md`;
2. przenosi karty i cytaty bez dodawania wymyślonych kwot, automatycznych warunków ani dat obowiązywania;
3. tworzy karty świadczeń, strony aktów, podstrony przepisów z jednostkami oraz stronę historii parametrów;
4. łączy artykuły między sobą na podstawie zarejestrowanych odesłań, przypisuje karty do artykułów i artykuły do kart;
5. zapisuje `data/eksport/` z sumami SHA-256, sprawdza schemat, uruchamia testy i generuje stronę w `dist/`.

Aby ręcznie wskazać datę przyjętą do określania bieżącej kwoty:

```powershell
py -3.10 aktualizuj_strone.py --socjal "C:\Users\Kamil\Documents\Fundacja\Socjal" --na-dzien 2026-10-20
```

Bez daty importer używa lokalnej bieżącej daty. Nie uznaje jednak samego końca okresu w tabeli za dowód obowiązywania przepisu w całym systemie prawa.

Gdy `Socjal` jest umieszczony bezpośrednio obok repozytorium, program znajdzie go automatycznie. Wówczas wystarczy:

```powershell
py -3.10 aktualizuj_strone.py
```

### Co pojawi się na stronie

* `/korzysci/`, `/korzysc/{id}/`: katalog i karty korzyści;
* `/akty/`, `/akt/{eli}/`: katalog i strony aktów;
* `/przepisy/`, `/przepis/{id}/`: indeks mapowanych artykułów, treści jednostek, odwołania oraz związane z nimi świadczenia;
* `/historia/`, `/historia/{parametr}/`: potwierdzone historyczne wartości z danych FUS;
* `/dane/`: JSON, CSV i metadane sum SHA-256; `socjal.json` zawiera ustrukturyzowaną mapę relacji.

**Uwaga:** mapa artykułów obejmuje jednostki z aktualnie ustrukturyzowanych danych `Dane/Mapa`, a nie automatycznie wszystkie przepisy widoczne w dowolnych załącznikach PDF. Tytuły aktów nieudokumentowane w metadanych pozostają neutralne. Osobne mapowanie aktów musi powstać wcześniej w źródłowym projekcie.

### Co jest traktowane jako weryfikowane

* Karty ręczne FUS i ich źródła mają oznaczenie `reczna_FUS`.
* Kandydaci odnalezieni przez analizę map są oznaczeni jako `automat`; nie są samodzielnym potwierdzeniem prawa do wypłaty.
* Ręcznie dodana karta w `Swiadczenia/`, której nie ma jeszcze w JSON, jest publikowana jako `do_ustalenia`, bez potwierdzonej kwoty, pod warunkiem że ma poprawny frontmatter z `typ: "karta_korzysci"`, `identyfikator` i `ustawa: "DU/ROK/NUMER"`.
* Notatki automatycznie wygenerowane przez mapowanie, rozpoznane po polu `generator`, nie tworzą duplikatów kart z JSON.
* Zmiany sekcji `## Komu przysługuje` i `## Ile wynosi` w ręcznych notatkach FUS będą uwzględniane; tekst prozatorski nie staje się automatycznie zweryfikowaną kwotą.
* Aktualne wartości wpisuje się wyłącznie wtedy, kiedy źródło dostarcza jednoznacznych danych. Nierozstrzygnięte przypadki pozostają oznaczone.

## 3. Opublikuj po sprawdzeniu

```powershell
py -3.10 aktualizuj_strone.py --socjal "C:\Users\Kamil\Documents\Fundacja\Socjal" --push
```

Parametr `--push` wysyła do GitHuba repozytorium strony wraz z wygenerowanym snapshotem. Skrypt wykonuje kontrolę adresu `origin`, gałęzi `main`, testy i kompilację przed zatwierdzeniem zmian. Nigdy nie wykonuje `force push` ani nie przechowuje tokenów GitHuba. Nie wysyła lokalnego folderu `Socjal`.

**GitHub Actions czyta tylko `data/eksport`.** To celowe: na serwerze GitHuba lokalny sejf Obsidiana nie istnieje. Publikacja po `git push` generuje witrynę ponownie z zatwierdzonego snapshotu. Workflow nie próbuje odczytywać `C:\...` ani pobierać prywatnych lokalnych plików.

Po poprawnej aktualizacji strona pozostaje pod https://youngtytus.github.io/ . Podgląd lokalny uruchomisz po zbudowaniu:

```powershell
py -3.10 -m http.server 8000 --directory dist
```

Otwórz `http://localhost:8000/`.

## 4. Zmiana samego sejfu Obsidian w przyszłości

Importer zna **obecną** strukturę źródeł. Jeśli w projekcie `Socjal` zmieni się schemat JSON, lokalizacja kart albo konwencja identyfikatorów, należy dostosować `scripts/importuj_socjal.py`. Program celowo przerywa działanie, gdy brakuje wymaganych plików, zamiast niepostrzeżenie wygenerować pustą witrynę.

Źródłem prawdy pozostaje folder `Socjal`. `data/eksport/` jest pochodną budowaną automatycznie, nie miejscem do ręcznej edycji prawa. Sam importer nie zmienia plików `Socjal`.

## 5. Diagnostyka

```powershell
py -3.10 -m unittest discover -s tests -v
npm ci
npm test
npm run waliduj
npm run build
```

Przy pierwszym uruchomieniu skrypt może sam wykonać `npm ci`; wymaga to dostępu do rejestru npm. Zależności natywne Node muszą być instalowane na systemie, na którym wykonywany jest build. Nie kopiuj `node_modules` pomiędzy Windowsem i Linuksem.

Walidacja poprawnego formatu, skrótów SHA-256 i spójności odnośników **nie zastępuje kontroli merytorycznej aktualności przepisów**.

### Dawny tryb eksportu

W razie potrzeby nadal można zbudować stronę z eksportu według kontraktu `strona-0.4`:

```powershell
py -3.10 aktualizuj_strone.py --eksport "C:\sciezka\eksport"
```

Nie używaj jednocześnie `--socjal` i `--eksport`. W nowym trybie szczegółowe mapy artykułów i historia parametrów pochodzą z dodatkowego `socjal.json`.
