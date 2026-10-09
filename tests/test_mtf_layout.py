"""MTF8.1 layout (RB 9 Oct): header over its numbers (same alignment), rupee money format."""
import datetime as dt,sys,tempfile,types,unittest,io,contextlib
from pathlib import Path
from openpyxl import load_workbook
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
import mtf_check as m
import mtf_portfolio_report as p
from test_mtf_breakeven import fixture
TODAY=dt.date(2026,10,9)
def model():
 r=fixture();r['loan']=m.Num(258386.43);r['current_lots']=r['fifo']['lots'];r['unpaid']=m.Num(176.32,m.ESTIMATED,'x');r['report_account']='DEMO'
 for x in r['rows']:x['Price']=2156 if x['Symbol']=='TCS' else 5770;x['Price source']='NSE demo'
 return r
class LayoutTests(unittest.TestCase):
 def setUp(self):
  self.d=tempfile.TemporaryDirectory();self.path=Path(self.d.name)/'MTF_Check.xlsx';self.r=model()
  self.rows=p.write_report(self.r,TODAY,self.path);self.s=load_workbook(self.path).active
 def tearDown(self):self.d.cleanup()
 def find(self,text):
  return next(c for row in self.s.iter_rows() for c in row if c.value==text)
 def test_headers_and_values_share_alignment(self):
  for head in ('Qty','Buy cost','Loan proxy','Interest MODEL','Pure BE now','Safe hold+exit+tax'):
   h=self.find(head);v=self.s.cell(h.row+1,h.column)
   self.assertEqual(h.alignment.horizontal,'center',head);self.assertEqual(v.alignment.horizontal,'center',head)
  m3=self.find('Metric')
  for c in range(2,2+len(self.rows)+1):
   self.assertEqual(self.s.cell(m3.row,c).alignment.horizontal,'center');self.assertEqual(self.s.cell(m3.row+1,c).alignment.horizontal,'center')
  self.assertEqual(self.find('Market value').alignment.horizontal,'left')
 def test_money_has_rupee_qty_and_days_do_not(self):
  self.assertIn('₹',self.find('Market value').offset(0,1).number_format)
  q=self.find('Qty');self.assertNotIn('₹',self.s.cell(q.row+1,q.column).number_format)
  self.assertNotIn('₹',self.s['F4'].number_format);self.assertIn('%',self.s['D4'].number_format)
  be=self.find('Pure BE now');self.assertIn('₹',self.s.cell(be.row+1,be.column).number_format)
 def test_terminal_rupee(self):
  buf=io.StringIO()
  with contextlib.redirect_stdout(buf):p.print_report(self.r,self.rows,types.SimpleNamespace(label='DEMO'),TODAY,types.SimpleNamespace(rate=.1249,buffer_days=30,settlement_buffer=3,tax_reserve=.208))
  out=buf.getvalue();self.assertTrue(p.RUPEE+'414,598.30' in out);self.assertIn('-'+p.RUPEE+'48,156.60',out)
class OwnCash(unittest.TestCase):
 def test_own_cash_is_cost_minus_loan(self):
  # RB 9 Oct: 'total value - loan = own money invested' -> B7 = D6 - B5 by default
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'x.xlsx';r=model();rows=p.write_report(r,TODAY,path)
   f=load_workbook(path).active;v=load_workbook(path,data_only=True).active
   own=p.number(r['open_cost_num'])-258386.43
   self.assertEqual(f['B7'].value,'=IFERROR(IF(AND(COUNT(D6,B5)=2,B5<=D6),D6-B5,"UNKNOWN"),"UNKNOWN")')
   self.assertAlmostEqual(v['B7'].value,own,places=2);self.assertAlmostEqual(v['B15'].value,own,places=2)
   self.assertAlmostEqual(v['B24'].value,sum(x['value'] for x in rows)-258386.43,places=2)
   self.assertEqual(v['A24'].value,'Aaj ki equity (market value - loan)')
   try:
    from pycel import ExcelCompiler
    xc=ExcelCompiler(filename=str(path))
    for ref in ('B7','B15','B24'):self.assertAlmostEqual(xc.evaluate('Breakeven!'+ref),v[ref].value,places=2)
   except ImportError:pass
  r=model();r['loan']=m.Num()
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'u.xlsx';p.write_report(r,TODAY,path);v=load_workbook(path,data_only=True).active
   self.assertEqual(v['B7'].value,'UNKNOWN');self.assertEqual(v['B24'].value,'UNKNOWN')   # unknown loan never becomes 0
 def test_known_own_cash_shown(self):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'x.xlsx';r=model();r['init_cash']=m.Num(150000.0);p.write_report(r,TODAY,path)
   v=load_workbook(path,data_only=True).active;self.assertEqual(v['B7'].value,150000);self.assertEqual(v['B15'].value,150000)
 def test_own_cash_remembered(self):
  import mtf_generic as g
  with tempfile.TemporaryDirectory() as d:
   a=types.SimpleNamespace(own_cash=150000.0);g.remember_own_cash(a,d)
   b=types.SimpleNamespace(own_cash=None);g.remember_own_cash(b,d);self.assertEqual(b.own_cash,150000.0)
   c=types.SimpleNamespace(own_cash=90000.0);g.remember_own_cash(c,d)
   e=types.SimpleNamespace(own_cash=None);g.remember_own_cash(e,d);self.assertEqual(e.own_cash,90000.0)
class TargetPlan(unittest.TestCase):
 """v33 (RB 9 Oct): small freeze + narrow columns; Section 4 per stock = target date, net P/L at the
 safe target (sold on the last day of the hold), net P/L if sold today."""
 def setUp(self):
  self.d=tempfile.TemporaryDirectory();self.path=Path(self.d.name)/'MTF_Check.xlsx';self.r=model()
  self.rows=p.write_report(self.r,TODAY,self.path);self.f=load_workbook(self.path).active;self.v=load_workbook(self.path,data_only=True).active
 def tearDown(self):self.d.cleanup()
 def head(self):return next(c for row in self.f.iter_rows() for c in row if c.value=='Safe hold+exit+tax')
 def test_calculate_target_keys(self):
  for r in self.rows:
   self.assertEqual(r['target_date'],TODAY+dt.timedelta(days=30))
   want=p.target_net(r['full'],r['qty'],r['cost'],r['past'],r['buy'],r['funded'],.1249,30,3,0)
   self.assertAlmostEqual(r['target_net'],want,places=6)
   self.assertGreaterEqual(r['target_net_tax'],2);self.assertLess(r['target_net_tax'],2+r['qty']*.05+1)
   self.assertGreaterEqual(r['target_net'],r['target_net_tax'])
  self.assertEqual(p.calculate(self.r,TODAY,days=60)[0]['target_date'],TODAY+dt.timedelta(days=60))
 def test_section4_cells(self):
  h=self.head();row=h.row;heads=[self.f.cell(row,c).value for c in range(1,14)]
  for want in ('Interest ab tak (MODEL)','Interest aaj se target date tak','Target date (aaj + 30 din)','Net P/L target pe (tax se pehle)','Net P/L target pe (tax reserve ke baad)','Net P/L AAJ becho'):self.assertIn(want,heads)
  for i,r in enumerate(self.rows):
   k=row+1+i;self.assertEqual(self.v.cell(k,1).value,r['symbol'])
   self.assertEqual(self.v.cell(k,5).value.date(),r['target_date']);self.assertEqual(self.f.cell(k,5).number_format,'dd-mmm-yyyy')
   for c,key in [(6,'past'),(7,'hold_interest'),(8,'target_net'),(9,'target_net_tax'),(10,'net_exit')]:
    self.assertAlmostEqual(self.v.cell(k,c).value,r[key],places=2);self.assertIn('₹',self.f.cell(k,c).number_format)
  tot=row+1+len(self.rows);self.assertEqual(self.v.cell(tot,1).value,'TOTAL')
  self.assertAlmostEqual(self.v.cell(tot,10).value,sum(r['net_exit'] for r in self.rows),places=2)
  try:
   from pycel import ExcelCompiler
   xc=ExcelCompiler(filename=str(self.path))
   for i,r in enumerate(self.rows):
    k=row+1+i
    for c in 'EFGHIJ':self.assertAlmostEqual(xc.evaluate('Breakeven!%s%d'%(c,k)),self.v[c+str(k)].value if c!='E' else (r['target_date']-dt.date(1899,12,30)).days,places=2)
  except ImportError:pass
 def test_negatives_red_in_the_cell(self):
  h=self.head();k=h.row+1;net_today=self.f.cell(k,10)
  self.assertLess(self.v.cell(k,10).value,0);self.assertEqual(net_today.font.color.rgb[-6:],'C00000')
  self.assertGreater(self.v.cell(k,8).value,0);self.assertNotEqual((self.f.cell(k,8).font.color.rgb or '')[-6:],'C00000')
  tot=self.f.cell(k+len(self.rows),10);self.assertEqual(tot.font.color.rgb[-6:],'C00000');self.assertTrue(tot.font.bold)
  pl=next(c for row in self.f.iter_rows() for c in row if c.value=='Price profit/loss')
  neg=[self.f.cell(pl.row,c) for c in range(2,2+len(self.rows)+1) if self.v.cell(pl.row,c).value<0]
  self.assertTrue(neg and all(c.font.color.rgb[-6:]=='C00000' for c in neg))
 def test_layout_compact(self):
  self.assertEqual(self.f.freeze_panes,'B1')                       # no frozen rows hiding the data
  self.assertTrue(all(d.width<=24 for d in self.f.column_dimensions.values()))
  self.assertEqual(self.f.column_dimensions['A'].width,24)
 def test_unknown_loan_gives_unknown_target_pnl(self):
  r=model();r['loan']=m.Num();path=Path(self.d.name)/'u.xlsx';rows=p.write_report(r,TODAY,path)
  self.assertTrue(all(x['target_net'] is None and x['target_net_tax'] is None for x in rows))
  v=load_workbook(path,data_only=True).active;h=next(c for row in v.iter_rows() for c in row if c.value=='Safe hold+exit+tax')
  self.assertEqual(v.cell(h.row+1,8).value,'UNKNOWN');self.assertEqual(v.cell(h.row+1+len(rows),8).value,'UNKNOWN')
 def test_terminal_lines(self):
  buf=io.StringIO()
  with contextlib.redirect_stdout(buf):p.print_report(self.r,self.rows,types.SimpleNamespace(label='DEMO'),TODAY,types.SimpleNamespace(rate=.1249,buffer_days=30,settlement_buffer=3,tax_reserve=.208))
  out=buf.getvalue();self.assertIn('Target date 08-Nov-2026 tak',out);self.assertIn('AAJ becho -> net P/L',out);self.assertIn('TOTAL net P/L at safe targets',out);self.assertIn('Interest kata hua: ab tak',out)
if __name__=='__main__':unittest.main()
