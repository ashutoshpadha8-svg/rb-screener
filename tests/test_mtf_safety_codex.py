#!/usr/bin/env python3
"""Independent required-behavior checks. Synthetic inputs, socket guard,
mocked account/broker; no production writes/orders. FAIL denotes a v29 gap.
Run next to source/mtf_check.py and source/journal.py; writes results JSON.
"""
import argparse,ast,datetime as dt,json,socket,sys,types
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]; SOURCE=ROOT;sys.path.insert(0,str(SOURCE))
def blocked(*a,**k): raise RuntimeError('AUDIT NETWORK BLOCKED')
socket.socket.connect=socket.socket.connect_ex=socket.create_connection=blocked
import mtf_check as m
# Reference original fees without importing unrelated project modules.
t=ast.parse((SOURCE/'journal.py').read_text()); ns={}
nodes=[n for n in t.body if isinstance(n,ast.Assign) and any(isinstance(x,ast.Name) and x.id in ('EXCH','DP') for target in n.targets for x in ast.walk(target)) or isinstance(n,ast.FunctionDef) and n.name=='fees']
exec(compile(ast.Module(body=nodes,type_ignores=[]),'<v29-fees>','exec'),ns)
sys.modules['journal']=types.SimpleNamespace(fees=ns['fees'])
D=dt.date(2026,10,7); results=[]
def check(name,condition,observed,required,group='remaining'):
 results.append({'case':name,'pass':bool(condition),'observed':observed,'required':required,'group':group});print(('PASS ' if condition else 'FAIL ')+name)
def tr(sym='AAA',qty=100,price=1000,side='BUY',ts='2026-09-01 10:00:00',product='MTF',charges=0,charges_ok=True,tid=''):
 stamp=m._ts(ts)
 return {'symbol':sym,'qty':qty,'price':price,'side':side,'ts':stamp,'date':stamp.date().isoformat() if stamp else None,'product':product,'charges':charges,'charges_ok':charges_ok,'exch':'NSE_EQ','tid':tid,'oid':'','isin':''}
def ledger(narr='MTF Interest for Period 24/09/2026 To 30/09/2026',debit=500,date='Oct 01, 2026',credit=0):
 return m.ledger_rows([dict(narration=narr,debit=debit,credit=credit,voucherdate=date)])
def run(trades=None,demat=None,current=None,prices=None,led=None,fail_trades=False,complete=True,**opts):
 a=argparse.Namespace(ledger=None,rate=m.MTF_RATE,loan=75000,unpaid_interest=400,own_cash=25000)
 for k,v in opts.items():setattr(a,k,v)
 def gettr(*a):
  if fail_trades:raise RuntimeError('synthetic trade-history failure')
  return list(trades if trades is not None else [tr()]),dict(complete=complete,notes=[])
 b=types.SimpleNamespace(holdings=lambda *a:list(demat if demat is not None else [{'symbol':'AAA','qty':100}]))
 def getq(sess,symbols):return {s:(p,m.VERIFIED,'synthetic live') for s,p in (prices if prices is not None else {'AAA':950}).items() if s in symbols}
 with patch.dict(sys.modules,{'broker_api':b}),patch.object(m,'dhan_trades',gettr),patch.object(m,'mtf_positions',lambda *a:current or {}),patch.object(m,'dhan_ledger',lambda *a: led if led is not None else ledger()),patch.object(m,'quotes',getq):
  return m.build(a,object(),D,dt.date(2024,4,1))
def data(n):return dict(value=n.value,status=n.status,known=n.known,partial=n.partial)
# Rechecks of previously reported behavior, separately count improvements.
r=run(loan=None)
check('L1_no_current_loan_stays_unknown',not r['loan'].known and not r['exit'].known,{'loan':data(r['loan']),'exit':data(r['exit'])},'Unknown loan/cash without --loan','legacy')
r=run(prices={})
check('L2_missing_quote_stays_unknown',not r['val'].known and not r['exit'].known,data(r['exit']),'Missing quote must not be zero','legacy')
f=m.fifo([tr(qty=4,price=60,side='SELL',ts='2026-10-01 09:30:00'),tr(qty=4,price=50,ts='2026-10-01 15:00:00')],D)
check('L3_true_intraday_fifo',not f['realised'].known and f['lots']['AAA'][0][1]==4,{'realised':data(f['realised']),'lots':f['lots']},'Uncovered morning sell/later buy remains open','legacy')
i=m.lot_interest([['2026-06-29',10,1000,0],['2026-09-27',10,1000,0]],.75,m.MTF_RATE,D)
check('L4_lot_dates_282_31',i.value==282.31,data(i),'Simplified declared lot-day estimate 282.31','legacy')
check('L5_dayfirst_ledger_date',m.parse_date('05/10/2026')==dt.date(2026,10,5),str(m.parse_date('05/10/2026')),'5 October','legacy')
kept,drop=m.dedupe([tr(tid='T1'),tr(tid='T1')])
check('L6_exact_duplicate_dropped',len(kept)==1 and drop==1,{'kept':len(kept),'dropped':drop},'Count same execution once','legacy')
r=run(demat=[])
check('L7_empty_demat_quarantines_old_lot',not r['val'].known and not r['rows'],data(r['val']),'Historical lots not valued as currently held','legacy')
r=run();other=run(led=m.ledger_rows([dict(narration='MTF Interest for Period 24/09/2026 To 30/09/2026',debit=500,credit=0,voucherdate='Oct 01, 2026'),dict(narration='Dividend CNC ONLY',debit=0,credit=100,voucherdate='Sep 05, 2026')]))
check('L8_cnc_dividend_not_mixed',r['period'].value==other['period'].value,{'base':data(r['period']),'extra_CNC':data(other['period'])},'Unrelated CNC income stays separate','legacy')
# Remaining source/status and accounting failures.
u=m.Num(100,m.UNKNOWN,'invalid fee amount')
tot=m.total([m.Num(200),-u])
check('R1_unknown_numeric_value_not_known',not u.known and not tot.known,{'unknown_input':data(u),'sum':data(tot)},'UNKNOWN must mean value None; partial=100 allowed, final dependent total UNKNOWN')
raw={'securityId':'1','tradingSymbol':'AAA','transactionType':'BUY','tradedQuantity':100,'tradedPrice':1000,'exchangeTime':'2026-09-01 10:00:00','exchangeSegment':'NSE_EQ','productType':'MTF','exchangeTradeId':'X1','sebiTax':1,'stt':100,'brokerageCharges':'unreadable','serviceTax':1,'exchangeTransactionCharges':3,'stampDuty':15}
x=m.parse_trade(raw);r=run(trades=[x])
check('R2_unreadable_trade_fee_blocks_net',not r['period'].known,{'fees':data(r['fifo']['charges']),'period':data(r['period'])},'Malformed required fee => period/net UNKNOWN; known charges subtotal separate')
empty_fee_raw={k:v for k,v in raw.items() if k not in ('sebiTax','stt','brokerageCharges','serviceTax','exchangeTransactionCharges','stampDuty')}
x=m.parse_trade(empty_fee_raw);r=run(trades=[x])
check('R3_absent_trade_fee_fields_not_verified_zero',not r['fifo']['charges'].known,{'charges_ok':x['charges_ok'],'fees':data(r['fifo']['charges'])},'Absent fee schema => UNKNOWN, or explicit documented estimator labelled ESTIMATED')
bad=m.ledger_rows([{'narration':'MTF Interest for Period 24/09/2026 To 30/09/2026','voucherdate':'Oct 01, 2026'}]);r=run(led=bad)
check('R4_missing_ledger_money_columns_not_zero',not r['paid'].known,{'row_bad':bool(bad.bad.iloc[0]),'paid':data(r['paid'])},'Required debit/credit columns absent => invalid source/UNKNOWN')
r=run(fail_trades=True,demat=[],current={},led=m.ledger_rows([]),loan=0,unpaid_interest=0)
check('R5_failed_history_not_verified_zero_totals',not r['val'].known and not r['period'].known,{'source':r['src'],'value':data(r['val']),'period':data(r['period']),'ok':r['ok']},'Failed essential history taints all dependent totals even when no rows parsed')
r=run(trades=[],complete=False,demat=[],current={},led=m.ledger_rows([]),loan=0,unpaid_interest=0)
check('R6_incomplete_empty_history_not_verified_zero',not r['period'].known,{'source':r['src'],'period':data(r['period'])},'Incomplete coverage must not become VERIFIED zero period P&L')
r=run(current={'AAA':20})
check('R7_current_mtf_qty_mismatch_quarantined',not r['val'].known,{'current_MTF_qty':20,'history_qty':100,'valued_qty':[a['Qty'] for a in r['rows']],'value':data(r['val']),'rec':r['rec']},'Positive current MTF 20 vs history 100 => unreconciled, do not value 100 as VERIFIED')
r=run(trades=[tr(product='')])
check('R8_guessed_product_status_propagates',r['val'].status!=m.VERIFIED and r['gross'].status!=m.VERIFIED,{'guessed':r['guessed'],'rec':r['rec'],'value':data(r['val']),'gross':data(r['gross'])},'Inferred product stays at least ESTIMATED through every dependent row/total')
r=run(trades=[tr(),tr(sym='BBB',qty=10,price=100,product='')],demat=[{'symbol':'AAA','qty':100},{'symbol':'BBB','qty':10}],prices={'AAA':950,'BBB':100})
check('R9_mixed_blank_product_not_silently_cnc',not r['val'].known,{'rec':r['rec'],'value':data(r['val'])},'Unclassified BBB may be MTF; request product proof/quarantine, do not label NOT MTF solely from missing tag')
try:
 parsed=m.parse_date('2026-99-99');error=None
except Exception as e:parsed=None;error=type(e).__name__
check('R10_invalid_iso_date_no_recursion',error is None and parsed is None,{'date':parsed,'error':error},'Invalid ISO date returns None/rejected input, no RecursionError')
# History response null != confirmed empty list.
b=types.SimpleNamespace(symbol_map=lambda *a:{},_call=lambda *a:None)
try:
 with patch.dict(sys.modules,{'broker_api':b}):ts,meta=m.dhan_trades(object(),D,D)
 observed={'rows':len(ts),'meta':meta};safe=not meta['complete']
except Exception as e:observed={'error':type(e).__name__};safe=True
check('R11_null_trade_history_not_complete_empty',safe,observed,'Invalid/null history response => source error/UNKNOWN, only validated [] proves empty')
# Informational requirements to keep separately from high priority issues.
r=run(led=ledger(narr='MTF Interest',debit=100,date='Oct 10, 2026'))
check('R12_future_ledger_voucher_not_counted_verified',not r['paid'].known or r['paid'].value!=100,{'paid':data(r['paid']),'source':r['src']},'Reject/filter invalid/out-of-window user statement rows with coverage disclosure')
r=run(led=m.ledger_rows([dict(narration='MTF Interest',debit=500,credit=0,voucherdate='Oct 01, 2026'),dict(narration='Pledge charges for MTF AAA',debit=100,credit=0,voucherdate='Oct 01, 2026')]))
check('R13_full_net_pledge_cost_not_omitted',not r['period'].known or 'partial' in r['period'].note.lower() or abs(r['period'].value-(-5000-500-400-r['fees'].value-100))<.01,{'period':data(r['period']),'unallocated':{k:data(v) for k,v in r['unalloc'].items()}},'Attributable MTF costs deducted once, or result explicitly partial/excludes-unallocated; not full economic net')
z=m.lot_interest([['2026-09-01',10,1000,0]],.75,0,D)
check('R14_valid_zero_rate_known_zero_estimate',z.known and z.value==0,data(z),'CLI accepts zero: explicit zero-rate model computes zero, not UNKNOWN')
(ROOT/'reports'/'verification').mkdir(parents=True,exist_ok=True)
(ROOT/'reports'/'verification'/'mtf_independent_codex.json').write_text(json.dumps({'meaning':'Required-behavior assertions, FAIL = unresolved supplied-v29 gap','date':'2026-10-07','external_sockets':'blocked','results':results},indent=2,default=str))
print(f'{sum(r["pass"] for r in results)} / {len(results)} passed (independent required behaviors)')
print(f'{sum(not r["pass"] for r in results)} failures')
sys.exit(0 if all(r['pass'] for r in results) else 1)
