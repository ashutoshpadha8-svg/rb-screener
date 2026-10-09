#!/usr/bin/env python3
"""CLI -> saved Excel regressions. Dummy broker/account, network forbidden."""
import contextlib,datetime as dt,io,os,socket,sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
def blocked(*a,**k):raise RuntimeError('OFFLINE MTF CLI GUARD')
socket.socket.connect=socket.socket.connect_ex=socket.create_connection=blocked
import mtf_check as m
class Today(dt.date):
 @classmethod
 def today(cls):return cls(2026,10,7)
def tr():
 return dict(symbol='AAA',qty=100,price=1000,side='BUY',ts=dt.datetime(2026,9,1,10,15,30),date='2026-09-01',product='MTF',charges=140,charges_ok=True,exch='NSE_EQ',tid='TRADE1',oid='ORDER1',isin='ISIN1',security_id='1')
class CliTests(unittest.TestCase):
 def run_report(self,*,fail_history=False,fail_ledger=False,fail_current=False,current_qty=100,missing_price=False,extra_pledge=False,empty=False,literal_narration=False):
  with tempfile.TemporaryDirectory(prefix='mtf-cli-dummy-') as d:
   acc=types.SimpleNamespace(activate=lambda:types.SimpleNamespace(token_ok=True,session=types.SimpleNamespace(broker='DHAN'),label='DUMMY',reports=d))
   ba=types.SimpleNamespace(holdings=lambda *a:[] if empty else [dict(symbol='AAA',qty=100)])
   def history(*a):
    if fail_history:raise RuntimeError('synthetic failed history')
    return ([] if empty else [tr()]),dict(complete=True,notes=[])
   def current(*a):
    if fail_current:raise RuntimeError('synthetic failed positions')
    return {} if empty else {'AAA':current_qty}
   def led(*a):
    if fail_ledger:raise RuntimeError('synthetic failed ledger')
    rows=[] if empty else [dict(narration='MTF Interest for Period 24/09/2026 To 30/09/2026',debit=500,credit=0,voucherdate='Oct 01, 2026')]
    if extra_pledge:rows.append(dict(narration='Pledge charges for MTF AAA',debit=100,credit=0,voucherdate='Oct 01, 2026'))
    if literal_narration:rows.append(dict(narration='=2+2',debit=100,credit=0,voucherdate='Oct 01, 2026'))
    return m.ledger_rows(rows)
   quote=lambda *a:{} if empty or missing_price else {'AAA':(950,m.VERIFIED,'dummy live quote')}
   argv=['mtf_check.py','--audit','--loan','0' if empty else '75000','--unpaid-interest','0' if empty else '400','--own-cash','0' if empty else '25000']
   stream=io.StringIO()
   with patch.dict(sys.modules,{'account':acc,'broker_api':ba}),patch.object(m,'dhan_trades',history),patch.object(m,'mtf_positions',current),patch.object(m,'dhan_ledger',led),patch.object(m,'quotes',quote),patch.object(sys,'argv',argv),patch.object(m.dt,'date',Today),contextlib.redirect_stdout(stream):
    code=m.main()
   path=Path(d)/'MTF_Audit.xlsx';self.assertTrue(path.exists())
   sheets=pd.read_excel(path,sheet_name=None)
   return code,sheets,stream.getvalue()
 def row(self,sheets,sheet,label):return sheets[sheet].set_index('Item').loc[label]
 def test_success_cash_and_cash_status(self):
  code,s,txt=self.run_report();self.assertEqual(code,0)
  cash=self.row(s,'MTF_Exit_Estimate','= Cash released')
  fees=-self.row(s,'MTF_Exit_Estimate','Sell fees')['Rs']
  self.assertAlmostEqual(cash['Rs'],95000-75000-400-fees);self.assertEqual(cash.Status,m.ESTIMATED)
 def test_export_preserves_execution_time(self):
  _,s,_=self.run_report();self.assertEqual(s['MTF_Trades'].ts.iloc[0],'2026-09-01 10:15:30')
  self.assertEqual(s['MTF_Trades'].tid.iloc[0],'TRADE1')
 def test_missing_quote_blank_not_zero(self):
  code,s,_=self.run_report(missing_price=True);self.assertEqual(code,2)
  n=self.row(s,'MTF_Exit_Estimate','= Cash released');self.assertEqual(n.Status,m.UNKNOWN);self.assertTrue(pd.isna(n.Rs))
 def test_failed_ledger_incomplete(self):
  code,s,txt=self.run_report(fail_ledger=True);self.assertEqual(code,2);self.assertIn('INCOMPLETE',txt)
  self.assertTrue(pd.isna(self.row(s,'MTF_Period','Comprehensive MTF net P&L').Rs))
 def test_failed_history_empty_cannot_verify_zero(self):
  code,s,_=self.run_report(fail_history=True,empty=True);self.assertEqual(code,2)
  for sheet,label in [('MTF_Open_Summary','Open cost (lots)'),('MTF_Period','MTF bought (history)'),('MTF_Period','Realised price P&L')]:
   n=self.row(s,sheet,label);self.assertEqual(n.Status,m.UNKNOWN);self.assertTrue(pd.isna(n.Rs))
 def test_current_quantity_mismatch_incomplete(self):
  code,s,_=self.run_report(current_qty=20);self.assertEqual(code,2)
  self.assertTrue(pd.isna(self.row(s,'MTF_Open_Summary','Value now').Rs))
 def test_positions_source_failure_propagates(self):
  code,s,_=self.run_report(fail_current=True);self.assertEqual(code,2)
  self.assertTrue(pd.isna(self.row(s,'MTF_Open_Summary','Open cost (lots)').Rs))
 def test_unallocated_cost_blocks_comprehensive_net(self):
  _,s,_=self.run_report(extra_pledge=True)
  n=self.row(s,'MTF_Period','Comprehensive MTF net P&L');self.assertEqual(n.Status,m.UNKNOWN);self.assertTrue(pd.isna(n.Rs))
  part=self.row(s,'MTF_Period','= MTF period subtotal');self.assertIn('PARTIAL',part.Note)
 def test_historical_paid_cost_not_deducted_again_on_exit(self):
  _,s,_=self.run_report(extra_pledge=True);n=self.row(s,'MTF_Exit_Estimate','= Cash released')
  self.assertEqual(n.Status,m.ESTIMATED);self.assertFalse(pd.isna(n.Rs))
 def test_invalid_date_rejected_before_account(self):
  acc=types.SimpleNamespace(activate=lambda:(_ for _ in ()).throw(AssertionError('must not activate')))
  with patch.dict(sys.modules,{'account':acc}),patch.object(sys,'argv',['mtf_check.py','--from','2026-99-99']),contextlib.redirect_stdout(io.StringIO()):self.assertEqual(m.main(),1)
 def test_invalid_numeric_rejected_before_account(self):
  acc=types.SimpleNamespace(activate=lambda:(_ for _ in ()).throw(AssertionError('must not activate')))
  with patch.dict(sys.modules,{'account':acc}),patch.object(sys,'argv',['mtf_check.py','--loan','nan']),contextlib.redirect_stdout(io.StringIO()):self.assertEqual(m.main(),1)
 def test_literal_ledger_text_not_formula(self):
  _,s,_=self.run_report(literal_narration=True);self.assertIn('=2+2',s['Ledger'].narration.tolist())
 def test_zero_rate_cli_model(self):
  v=m.lot_interest([['2026-09-01',100,1000,140]],.75,0,Today.today());self.assertTrue(v.known);self.assertEqual(v.value,0)
if __name__=='__main__':unittest.main()
