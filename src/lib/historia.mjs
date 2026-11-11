// Etykiety dla archiwum historii kwot (/historia/). Dane bez zmian: tylko nazwy po polsku zamiast kluczy.
import { kwotaPL, wielka } from './format.mjs';

const NAZWY = {
  dodatek_pielegnacyjny: 'Dodatek pielęgnacyjny',
  dodatek_sierota_zupelna: 'Dodatek dla sieroty zupełnej',
  krok_zaokraglenia_niepelnego_miesiaca: 'Zaokrąglenie kwoty za niepełny miesiąc',
  kryterium_dochodowe_pierwsze_dziecko: 'Kryterium dochodowe przy pierwszym dziecku',
  kryterium_dochodowe_pierwsze_dziecko_niepelnosprawnosc: 'Kryterium dochodowe przy pierwszym dziecku z niepełnosprawnością',
  kwota_na_rodzica_opieka_naprzemienna: 'Kwota na rodzica przy opiece naprzemiennej',
  minimum_emerytura_renta_calkowita_rodzinna: 'Najniższa emerytura, renta z tytułu całkowitej niezdolności do pracy i renta rodzinna',
  minimum_renta_czesciowa: 'Najniższa renta z tytułu częściowej niezdolności do pracy',
  swiadczenie_wychowawcze_kwota_pelna: 'Świadczenie wychowawcze, pełna kwota',
  zasilek_pogrzebowy_limit: 'Zasiłek pogrzebowy: górna granica',
  zasilek_pogrzebowy_mnoznik: 'Zasiłek pogrzebowy: mnożnik',
};
const TYPY = {
  kwota_poczatkowa_ustawowa: 'kwota początkowa z ustawy',
  kwota_ogloszona: 'kwota ogłoszona (waloryzacja)',
  kwota_ustawowa: 'kwota z ustawy',
  kwota_ogloszona_szczegolna: 'kwota ogłoszona w trybie szczególnym',
  potwierdzone_z_aktu: 'z aktu prawnego',
  obliczenie_z_reguly_i_pelnej_stawki: 'obliczona z reguły i pełnej stawki',
  kwota_obliczona_z_parametru_i_normy: 'obliczona z parametru i normy',
};
const JEDNOSTKI = {
  PLN_miesiecznie: 'miesięcznie',
  PLN_miesiecznie_na_dziecko: 'miesięcznie na dziecko',
  PLN_miesiecznie_na_rodzica: 'miesięcznie na rodzica',
  PLN_jednorazowo: 'jednorazowo',
  PLN_miesiecznego_dochodu_na_osobe: 'miesięcznego dochodu na osobę',
  PLN_krok_zaokraglenia_w_gore: 'krok zaokrąglenia w górę',
  procent_przecietnego_wynagrodzenia: 'przeciętnego wynagrodzenia',
};
const zKlucza = (k) => wielka(String(k ?? '').replaceAll('_', ' '));

export const nazwaParametru = (k) => NAZWY[k] ?? zKlucza(k);
export const typWpisu = (t, wyliczona) => (wyliczona ? 'wyliczona z parametru' : TYPY[t] ?? (t ? String(t).replaceAll('_', ' ') : 'nie opisano'));
export const opisJednostki = (j) => (JEDNOSTKI[j] ?? (j?.startsWith('PLN') ? '' : String(j ?? '').replaceAll('_', ' ')));
/** Wartość z jednostką: kwoty w zł zapisem witryny, pozostałe (np. procent) jak w źródle. */
export function wartosc(r) {
  if (r.jednostka?.startsWith('PLN')) return kwotaPL(`${r.wartosc} zł`);
  if (r.jednostka?.startsWith('procent')) return `${String(r.wartosc).replace('.', ',')} %`;
  return String(r.wartosc);
}
/** Najnowszy wpis (największa data „od”). */
export const ostatni = (lista) => [...lista].sort((a, b) => String(b.od).localeCompare(String(a.od)))[0];
