"""Independent semantic regressions; temporary fixtures only, no production writes."""
import copy,json,tempfile,unittest
from pathlib import Path
from scripts.importuj_socjal import bez_kwoty,karty_analiz_eli,uporzadkuj_prezentacje

def card():
 return {'id':'test','nazwa':'Test świadczenia','ile':bez_kwoty(),'status':'obowiazuje','do_kiedy':[],'sytuacje':[],'sytuacje_zrodlo':None,'flagi':[]}
def amount(label,value):return {'etykieta':label,'wartosc':value}
def timeline(variants,end=None):
 return {'wartosc':None,'warianty':variants,'od':'2026-01-01','do':end,'rodzaj_zmiany':'pierwszy_znany_wpis','poprzednia':None,'roznica':None,'dowod':{'eli':'DU/2026/1','przepis':'art.1','cytat':'dowód'}}
def rule(id,name,type,expression,start='2026-01-01',end=None):
 return {'id':id,'swiadczenie':'DU-2026-1/S001','nazwa':name,'typ':type,'wyrazenie':expression,'od':start,'do':end,'zaokraglenie':None,'ustalenia':['DU-2026-1/U001']}
def imported(rules):
 with tempfile.TemporaryDirectory() as folder:
  root=Path(folder);d=root/'Analizy ELI/DU-2026-1/dane';d.mkdir(parents=True)
  values={'stan.json':{'eli':'DU/2026/1','status':'wymaga_uzupelnienia'},'swiadczenia.json':{'swiadczenia':[{'id':'DU-2026-1/S001','nazwa':'Próba','rodzaj':'swiadczenie','forma':'pieniezne','adresat':'Osoba','opis':'Opis','okres_od':None,'okres_do':None,'ustalenia':['DU-2026-1/U001']}]},'ustalenia.json':{'ustalenia':[{'id':'DU-2026-1/U001','akt_eli':'DU/2026/1','jednostka':'art.1','wersja':{},'cytat':'Dowód przyznania','zrodlo_sha256':'a'*64,'strona_pdf':1}]},'reguly_kwot.json':{'reguly':rules}}
  for name,v in values.items():(d/name).write_text(json.dumps(v),encoding='utf-8')
  result=[];karty_analiz_eli(root,'2026-10-31',result,{}, {},set());return result[0]

class PresentationEdgeTests(unittest.TestCase):
 def test_mixed_minimum_and_full_payment_variants_do_not_promote_the_floor(self):
  k=card();vs=[amount('najniższa kwota','1000 zł'),amount('kwota stała wariantu B','2000 zł')]
  k['ile']['aktualna']={'wartosc':None,'warianty':copy.deepcopy(vs),'od':'2026-01-01','do':None};k['ile']['os_czasu']=[timeline(vs)]
  uporzadkuj_prezentacje([k],'2026-10-31')
  self.assertEqual(k['ile']['aktualna']['warianty'],[vs[1]],'Mieszany wariant minimum musi trafić do progów.')
  self.assertTrue(k['ile']['progi'])
 def test_current_floor_does_not_relabel_full_payment_history(self):
  k=card();vs=[amount('najniższa kwota','1000 zł')];k['ile']['aktualna']={'wartosc':None,'warianty':vs,'od':'2026-01-01','do':None}
  old=timeline([amount('szczególny ryczałt ustawowy','800 zł')],'2025-12-31');old['od']='2025-01-01';k['ile']['os_czasu']=[old,timeline(vs)]
  uporzadkuj_prezentacje([k],'2026-10-31');self.assertEqual(k['ile']['os_czasu'],[old],'Nie zmieniać pełnej wcześniejszej kwoty w minimum.')
 def test_minimum_without_timeline_keeps_its_value(self):
  k=card();k['ile']['aktualna']={'wartosc':None,'warianty':[amount('najniższa kwota','1000 zł')],'od':'2026-01-01','do':None}
  uporzadkuj_prezentacje([k],'2026-10-31');self.assertTrue(k['ile']['progi'],'Nie usuwać jedynej znanej wartości.')
 def test_past_special_deadline_does_not_override_relative_standard_branch(self):
  k=card();k['do_kiedy']=[{'rodzaj':'termin_wniosku','do':'2024-01-31','data':'2024-01-31','opis':'Specjalny dawny wariant'},{'rodzaj':'termin_wniosku','do':None,'data':None,'opis':'Zasadniczo 12 miesięcy od indywidualnego zdarzenia'}]
  uporzadkuj_prezentacje([k],'2026-10-31');self.assertEqual(k['status'],'obowiazuje','Nie pomijać nieustalonej/względnej gałęzi naboru.')
 def test_income_threshold_is_not_maximum_payment(self):
  # Real pattern DU/2007/1378/G003: criterion1665, benefit cap1000 has unknown start.
  k=imported([rule('DU-2026-1/G001','Reguła wypłaty','wzor','min(alimenty;1000 zł) minus przekroczenie progu'),rule('DU-2026-1/G002','Górny limit wypłaty','limit','1000 zł',start=None),rule('DU-2026-1/G003','Kryterium dochodowe, nie kwota świadczenia','limit','1665 zł',start='2026-10-01')])
  row=next(p for p in k['ile']['progi']if 'Kryterium' in p['przepis'])['wpisy'][0];self.assertNotEqual(row.get('_rodzaj'),'maksimum','Nie przedstawiać1665jako maksimum wypłaty.')
 def test_childcare_eligible_cost_is_not_subsidy_amount(self):
  # Real pattern DU/2024/858/G004: qualifying fee2200 vs subsidy1500/1900.
  k=imported([rule('DU-2026-1/G001','Kwota dopłaty','wzor','min(1500 lub1900 zł;opłata), z limitem kosztu pobytu'),rule('DU-2026-1/G002','Limit kosztu pobytu, nie wypłata','limit','2200 zł',start='2026-04-01',end='2027-03-31')])
  self.assertNotEqual(k['ile']['progi'][0]['wpisy'][0].get('_rodzaj'),'maksimum','2200 to warunek kosztu pobytu.')
 def test_same_start_variants_keep_own_end_dates(self):
  k=imported([rule('DU-2026-1/G001','Wariant A zakończony','kwota','1000 zł',end='2026-06-30'),rule('DU-2026-1/G002','Wariant B nadal','kwota','2000 zł')])
  self.assertIsNotNone(k['ile']['aktualna'],'Koniec A nie zamyka B.')
  self.assertEqual(k['ile']['aktualna']['warianty'],[amount('Wariant B nadal','2000,00 zł')])
 def test_formula_is_retained_alongside_confirmed_amount(self):
  k=imported([rule('DU-2026-1/G001','Pełny miesiąc','kwota','800 zł'),rule('DU-2026-1/G002','Niepełny miesiąc','wzor','Kwota miesięczna/liczba dni miesiąca razy dni prawa')])
  self.assertEqual(k['ile']['aktualna']['wartosc'],'800,00 zł');self.assertIn('dni prawa',k['ile']['regula']['opis'])
