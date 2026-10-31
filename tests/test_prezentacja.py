import copy, unittest
from scripts.importuj_socjal import uporzadkuj_prezentacje, bez_kwoty

def card():
 return {'id':'test','nazwa':'Renta rodzinna','ile':bez_kwoty(),'status':'obowiazuje','do_kiedy':[],
         'sytuacje':[],'sytuacje_zrodlo':None,'flagi':[]}
class PresentationTests(unittest.TestCase):
 def test_minimum_is_not_payment_but_keeps_proof_and_history(self):
  k=card();w={'wartosc':None,'warianty':[{'etykieta':'najniższa renta','wartosc':'1978,49 zł'}],
             'od':'2026-03-01','do':None,'dowod':{'eli':'MP/2026/220','cytat':'dowód'}}
  k['ile']['aktualna']=copy.deepcopy(w);k['ile']['os_czasu']=[copy.deepcopy(w)]
  uporzadkuj_prezentacje([k],'2026-10-31')
  self.assertIsNone(k['ile']['aktualna']);self.assertEqual(k['ile']['os_czasu'],[])
  row=k['ile']['progi'][0]['wpisy'][0]
  self.assertEqual(row['wartosc'],'1978,49 zł');self.assertEqual(row['dowod'],w['dowod']);self.assertEqual(row['_rodzaj'],'minimum')
 def test_target_of_top_up_is_not_minimum_top_up(self):
  k=card();k['ile']['aktualna']={'wartosc':'1978,49 zł','_mechanizm':'kwota_do_minimum'}
  k['ile']['os_czasu']=[{'wartosc':'1978,49 zł','warianty':None,'dowod':{}}]
  uporzadkuj_prezentacje([k],'2026-10-31')
  self.assertNotIn('_rodzaj',k['ile']['progi'][0]['wpisy'][0]);self.assertIsNone(k['ile']['aktualna'])
 def test_closed_application_is_not_closed_claim(self):
  k=card();k['do_kiedy']=[{'rodzaj':'termin_wniosku','do':'2022-11-30','data':None}]
  uporzadkuj_prezentacje([k],'2026-10-31')
  self.assertEqual(k['status'],'do_ustalenia');self.assertIn('rozliczenia',k['flagi'][0])
 def test_open_or_relative_application_does_not_close_support(self):
  for row in [{'rodzaj':'termin_wniosku','data':None},{'rodzaj':'termin_wniosku','do':'2027-01-01','data':None}]:
   k=card();k['do_kiedy']=[row];uporzadkuj_prezentacje([k],'2026-10-31');self.assertEqual(k['status'],'obowiazuje')
 def test_full_amount_stays_full_amount(self):
  k=card();k['ile']['aktualna']={'wartosc':'800 zł','warianty':None}
  uporzadkuj_prezentacje([k],'2026-10-31');self.assertEqual(k['ile']['aktualna']['wartosc'],'800 zł')
