#!/usr/bin/env python3
"""Current holdings, downloaded broker statements and identifier replay cases."""
import argparse,datetime as dt,json,os,socket,sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
def blocked(*a,**k):raise RuntimeError('OFFLINE')
socket.socket.connect=socket.create_connection=blocked
import mtf_check as m
D=dt.date(2026,10,7)
H=[dict(symbol='TCS',qty=52,avg_price=3082.09),dict(symbol='PERSISTENT',qty=46,avg_price=5528.91)]
def args(**kw):
 d=dict(ledger=None,loan=None,rate=m.MTF_RATE,unpaid_interest=None,own_cash=None,confirm_requests={},confirmation_path=None,account_key='DUMMY');d.update(kw);return argparse.Namespace(**d)
def tr(**kw):
 d=dict(symbol='TCS',qty=52,price=3082.09,side='BUY',ts=m._ts('2026-09-01 10:00:00'),date='2026-09-01',product='MTF',charges=10,charges_ok=True,exch='NSE_EQ',tid='SAME',oid='O1',security_id='1');d.update(kw);return d
def build(a=None,history=None,holdings=None,fail=False):
 def get(*x):
  if fail:raise RuntimeError('synthetic failure')
  return history or [],dict(complete=True,notes=[])
 led=m.ledger_rows([dict(narration='MTF Interest for Period 24/09/2026 To 30/09/2026',debit=653.34,credit=0,voucherdate='Oct 01, 2026')])
 ba=types.SimpleNamespace(holdings=lambda *x:H if holdings is None else holdings)
 px={'TCS':(2100,m.VERIFIED,'dummy quote'),'PERSISTENT':(5521,m.VERIFIED,'dummy quote')}
 with patch.dict(sys.modules,{'broker_api':ba}),patch.object(m,'dhan_trades',get),patch.object(m,'mtf_positions',lambda *x:{}),patch.object(m,'dhan_ledger',lambda *x:led),patch.object(m,'quotes',lambda sess,syms:{s:px[s] for s in syms if s in px}):return m.build(a or args(),object(),D,dt.date(2024,1,1))
class Tests(unittest.TestCase):
 def confirmed(self,**kw):return build(args(confirm_requests={'TCS':52,'PERSISTENT':46},**kw))
 def test_missing_history_is_unknown_product(self):
  r=build();self.assertTrue(all(x['Status']==m.UNKNOWN for x in r['rec']));self.assertFalse(r['val'].known)
 def test_confirmed_qty_present(self):self.assertEqual([(r['Symbol'],r['Qty']) for r in self.confirmed()['rows']],[('PERSISTENT',46),('TCS',52)])
 def test_correct_current_arithmetic(self):
  r=self.confirmed();self.assertAlmostEqual(r['open_cost_num'].value,414598.54);self.assertAlmostEqual(r['val'].value,363166);self.assertAlmostEqual(r['gross'].value,-51432.54)
 def test_no_lot_dates_invented(self):self.assertTrue(all(r['First buy'] is None and not r['Interest est. (Rs)'].known for r in self.confirmed()['rows']))
 def test_confirmation_not_historical_reclassification(self):
  r=build(args(confirm_requests={'TCS':52,'PERSISTENT':46}),[tr(product='CNC')]);self.assertEqual(r['mtf'],[]);self.assertFalse(r['period'].known)
 def test_phantom_old_stock_does_not_hide_current_stocks(self):
  r=build(args(confirm_requests={'TCS':52,'PERSISTENT':46}),[tr(symbol='BDL',qty=145)]);self.assertTrue(r['val'].known);self.assertFalse(r['period'].known)
 def test_failed_history_current_still_visible_period_unknown(self):
  r=build(args(confirm_requests={'TCS':52,'PERSISTENT':46}),fail=True);self.assertTrue(r['val'].known);self.assertFalse(r['period'].known);self.assertFalse(r['ok'])
 def test_unclassified_third_holding_blocks_complete_total(self):
  r=build(args(confirm_requests={'TCS':52,'PERSISTENT':46}),holdings=H+[dict(symbol='AAA',qty=1,avg_price=100)]);self.assertFalse(r['val'].known);self.assertEqual(r['val'].partial,363166)
 def test_mixed_product_average_not_used(self):
  r=build(args(confirm_requests={'TCS':10,'PERSISTENT':46}));x=next(x for x in r['rows'] if x['Symbol']=='TCS');self.assertFalse(x['Open cost (Rs)'].known);self.assertEqual(x['Value (Rs)'].value,21000)
 def test_loan_does_not_fix_historical_lots(self):
  r=self.confirmed(loan=200000,unpaid_interest=747);self.assertTrue(r['exit'].known);self.assertFalse(r['period'].known)
 def saved(self,path):m.confirmed_inventory(args(confirm_requests={'TCS':52},confirmation_path=path),{'TCS':H[0]},D)
 def test_confirmation_saved_and_reused(self):
  with tempfile.TemporaryDirectory() as d:
   p=os.path.join(d,'c.json');self.saved(p);a,_=m.confirmed_inventory(args(confirmation_path=p),{'TCS':H[0]},D);self.assertIn('TCS',a)
 def test_confirmation_account_mismatch_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   p=os.path.join(d,'c.json');self.saved(p)
   with self.assertRaises(ValueError):m.confirmed_inventory(args(confirmation_path=p,account_key='OTHER'),{'TCS':H[0]},D)
 def test_qty_change_invalidates(self):
  with tempfile.TemporaryDirectory() as d:
   p=os.path.join(d,'c.json');self.saved(p);a,msg=m.confirmed_inventory(args(confirmation_path=p),{'TCS':dict(H[0],qty=51)},D);self.assertFalse(a);self.assertTrue(msg)
 def test_cost_change_invalidates(self):
  with tempfile.TemporaryDirectory() as d:
   p=os.path.join(d,'c.json');self.saved(p);a,_=m.confirmed_inventory(args(confirmation_path=p),{'TCS':dict(H[0],avg_price=3000)},D);self.assertFalse(a)
 def test_expired_confirmation_not_used(self):
  with tempfile.TemporaryDirectory() as d:
   p=os.path.join(d,'c.json');self.saved(p);a,_=m.confirmed_inventory(args(confirmation_path=p),{'TCS':H[0]},D+dt.timedelta(days=8));self.assertFalse(a)
 def test_bad_confirmation_input(self):
  for v in ['../TCS','TCS:0','TCS:nan','TCS:1.5','TCS,TCS']:
   with self.assertRaises(ValueError):m.parse_confirmations(v)
 def test_same_id_across_dates_not_removed(self):
  out,n=m.dedupe([tr(),tr(date='2026-09-02',ts=m._ts('2026-09-02 10:00:00'))]);self.assertEqual((len(out),n),(2,0))
 def test_same_id_across_stocks_not_removed(self):
  out,n=m.dedupe([tr(),tr(symbol='PERSISTENT',security_id='2')]);self.assertEqual((len(out),n),(2,0))
 def test_exact_execution_replay_removed(self):self.assertEqual(m.dedupe([tr(),tr()])[1],1)
 def test_no_reference_same_second_fills_kept(self):self.assertEqual(m.dedupe([tr(tid='',oid=''),tr(tid='',oid='')])[1],0)
 def test_known_part_export_column(self):
  f=m.flatten([{'x':m.Num(None,m.UNKNOWN,partial=123)}]);self.assertTrue(m.pd.isna(f.x.iloc[0]));self.assertEqual(f['x known part'].iloc[0],123)
 def test_current_statement_loan(self):
  f=m.ledger_rows([dict(narration='Net MTF Funding by Dhan',debit=0,credit=261888.33,voucherdate='Oct 07, 2026')]);n=m.statement_loan(f,D);self.assertEqual(n.value,261888.33);self.assertEqual(m.money_in_out(f),(0,0))
 def test_stale_funding_not_current_loan(self):
  f=m.ledger_rows([dict(narration='Net MTF Funding by Dhan',debit=0,credit=1000,voucherdate='Oct 06, 2026')]);self.assertFalse(m.statement_loan(f,D).known)
 def test_disguised_excel_negative_debit_import(self):
  with tempfile.TemporaryDirectory() as d:
   p=os.path.join(d,'Ledger.csv');m.pd.DataFrame([['Client ID','DUMMY',None,None,None],['Date','Transaction ID','Narration','Debit','Credit'],['Oct 07, 2026','V1','MTF Interest',-100,0]]).to_excel(p+'.xlsx',header=False,index=False);os.rename(p+'.xlsx',p)
   f=m.read_ledger_file(p);self.assertEqual(f.debit.iloc[0],100);self.assertFalse(f.bad.iloc[0])
 def test_funding_ambiguous_not_used(self):
  f=m.ledger_rows([dict(narration='Net MTF Funding by Dhan',debit=0,credit=n,voucherdate='Oct 07, 2026') for n in [1000,2000]]);self.assertFalse(m.statement_loan(f,D).known)
 def test_mtf_sell_brokerage_not_zero_cnc(self):
  import journal
  self.assertAlmostEqual(m.mtf_sell_fees(100000)-journal.fees('DHAN','SELL',100000)[0],41.30)
 def file_fixture(self,d,value=1012.49):
  master=Path(d)/'master.csv'
  m.pd.DataFrame([dict(SEM_EXM_EXCH_ID='NSE',SEM_INSTRUMENT_NAME='EQUITY',SEM_TRADING_SYMBOL='TCS',SEM_CUSTOM_SYMBOL='Tata Consultancy Services',SM_SYMBOL_NAME='TATA CONSULTANCY SERVICES LIMITED')]).to_csv(master,index=False)
  path=Path(d)/'trades.csv'
  row={'Date':'2026-10-07','Time':'10:00:00','Name':'Tata Consultancy Services','Buy/Sell':'BUY','Order':'MTF','Exchange':'NSE','Segment':'Equity','Quantity/Lot':100,'Trade Price':10.12,'Trade Value':value,'Status':'Traded'}
  m.pd.DataFrame([row,row]).to_csv(path,index=False)
  return path,master
 def test_csv_retains_no_id_rows(self):
  with tempfile.TemporaryDirectory() as d:
   p,master=self.file_fixture(d);t,meta=m.read_trade_file(str(p),str(master),D,D);self.assertEqual(len(t),2);self.assertTrue(meta['complete']);self.assertEqual(t[0]['product'],'MTF');self.assertFalse(t[0]['charges_ok'])
 def test_csv_rounding_preserves_trade_value(self):
  with tempfile.TemporaryDirectory() as d:
   p,master=self.file_fixture(d);t,_=m.read_trade_file(str(p),str(master),D,D);self.assertAlmostEqual(t[0]['qty']*t[0]['price'],1012.49)
 def test_bad_trade_value_not_complete(self):
  with tempfile.TemporaryDirectory() as d:
   p,master=self.file_fixture(d,1200);_,meta=m.read_trade_file(str(p),str(master),D,D);self.assertFalse(meta['complete'])
 def test_stale_trade_file_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   p,master=self.file_fixture(d);new=Path(d)/'TRADE_HISTORY_CSV_12345_2024-01-01_2026-10-06_0_.csv';p.rename(new)
   with self.assertRaises(ValueError):m.read_trade_file(str(new),str(master),dt.date(2024,1,1),D)
 def test_other_account_file_rejected(self):
  with self.assertRaises(ValueError):m.validate_statement_account('TRADE_HISTORY_CSV_12345_2024-01-01_2026-10-07_0_.csv','DHAN_98765',True)
 def test_conflicting_execution_payload_incomplete(self):
  raw=dict(securityId='1',tradingSymbol='TCS',exchangeTime='2026-10-07 10:00:00',exchangeSegment='NSE_EQ',productType='MTF',exchangeTradeId='X1',orderId='O1',transactionType='BUY',tradedQuantity=10,tradedPrice=100)
  count=[0]
  def get(*a):
   count[0]+=1;return [raw,dict(raw,tradedQuantity=11)] if count[0]==1 else []
  ba=types.SimpleNamespace(symbol_map=lambda *a:{'TCS':{'id':'1'}},_call=get)
  with patch.dict(sys.modules,{'broker_api':ba}):t,meta=m.dhan_trades(object(),D,D)
  self.assertEqual(len(t),2);self.assertFalse(meta['complete'])
 def test_delivery_exit_closes_mtf_origin(self):
  f=m.fifo_by_buy_origin([tr(qty=6,price=100),tr(side='SELL',qty=6,price=90,product='CNC',ts=m._ts('2026-09-02 10:00:00'),date='2026-09-02')],D)
  self.assertEqual(f['lots'],{});self.assertEqual(f['realised'].value,-60);self.assertEqual(f['realised'].status,m.ESTIMATED);self.assertEqual(len(f['cross_matches']),1)
 def test_cnc_origin_profit_not_in_mtf_price_pnl(self):
  f=m.fifo_by_buy_origin([tr(qty=2,price=100,product='CNC'),tr(side='SELL',qty=2,price=90,product='CNC',ts=m._ts('2026-09-02 10:00:00'),date='2026-09-02')],D);self.assertEqual(f['matched'],0)
 def test_fifo_mixed_origins_only_counts_mtf_part(self):
  f=m.fifo_by_buy_origin([tr(qty=2,price=100,product='CNC'),tr(qty=3,price=110,ts=m._ts('2026-09-02 10:00:00'),date='2026-09-02'),tr(side='SELL',qty=4,price=120,product='CNC',ts=m._ts('2026-09-03 10:00:00'),date='2026-09-03')],D);self.assertEqual(f['matched'],20);self.assertEqual(f['lots']['TCS'][0][1],1)
 def test_intraday_does_not_join_carried_fifo(self):
  f=m.fifo_by_buy_origin([tr(product='INTRADAY')],D);self.assertEqual(f['lots'],{});self.assertEqual(f['bought'],0)
 def test_uncovered_cross_product_sell_stays_unknown(self):
  f=m.fifo_by_buy_origin([tr(side='SELL',product='CNC')],D);self.assertFalse(f['realised'].known)
 def test_absent_trade_id_with_same_order_cannot_drop_fill(self):
  self.assertEqual(m.dedupe([tr(tid=''),tr(tid='')])[1],0)
if __name__=='__main__':unittest.main()
