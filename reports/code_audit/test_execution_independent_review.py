"""Independent regressions for updated execution code. Fake HTTP + temp/in-memory files only.
Exit 1 means a safety expectation failed. Production files and accounts are untouched.
"""
from pathlib import Path
import importlib.util,sys
import pandas as pd
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('supplied_execution_tests',ROOT/'tests/test_execution.py')
tv=importlib.util.module_from_spec(spec)
spec.loader.exec_module(tv)
ba,at=tv.ba,tv.at
RESULTS=[]
def check(name,condition,detail):
 RESULTS.append((name,bool(condition)))
 print(('PASS' if condition else 'FAIL')+' '+name+' | '+str(detail),flush=True)

def portfolio(names):
 return pd.DataFrame([dict(symbol=s,swing_qty=0,investing_qty=0,momentum_qty=10,
  entry_price=100.,entry_date='2026-09-01',strategy='Momentum',mode='LIVE',product='CNC',order_id='',note='') for s in names])
def actions(symbol):
 return pd.DataFrame([{'Ticker':symbol,'act':'BUY','Strategy Overlap':'Momentum only','Amount (Rs)':''}])

def main():
 # 1: An aged UNKNOWN is found as still PENDING. It must keep blocking.
 f=tv.FakeDhan('lost_after_accept',show=False);s=tv.fresh(f)
 tv.run(s);tv.age_ledger(1);f.show=True
 result=tv.run(s)
 check('Recovered previous-day PENDING must not cause a second POST',f.posts==1 and result=='BLOCKED',{'result':result,'POSTs':f.posts})

 # 2: A SELL was accepted but none of the holding has sold yet.
 f=tv.FakeDhan('ok');s=tv.fresh(f);tv.run(s,side='SELL')
 names=['ABC']+['H%02d'%i for i in range(19)]
 oldsectors=at._sectors
 at._sectors=lambda:{x:'Sector'+str(i) for i,x in enumerate(names+['NEW'])}
 new,skip=at.plan(actions('NEW'),{'NEW':(100.,'mock')},portfolio(names),s)
 check('Pending SELL must not free a 20-position portfolio slot',len(new)==0,{'still_held':20,'proposed_BUYs':len(new),'possible_total':20+len(new)})
 at._sectors=oldsectors

 # 3: Backend committed, but HTTP 500 is the response seen by the client.
 class AcceptedThen500(tv.FakeDhan):
  def __call__(self,method,url,**kw):
   result=super().__call__(method,url,**kw)
   if method=='POST':return tv.Resp(500,{'errorMessage':'upstream response failure'})
   return result
 f=AcceptedThen500('ok');s=tv.fresh(f)
 first,second=tv.run(s),tv.run(s)
 check('Ambiguous HTTP 500 must not release the intent for resubmission',f.posts==1,{'first':first,'second':second,'accepted_orders':len(f.orders),'POSTs':f.posts})

 # 4: Order response reports 3 filled; the separate trade-book view is lagging.
 def lagging_trades(method,url,**kw):
  path=url.replace(ba.DHAN_BASE,'')
  if method=='GET' and path=='/orders/5501':
   return tv.Resp(200,dict(orderId='5501',orderStatus='CANCELLED',filledQty=3,averageTradedPrice=101.,remainingQuantity=0))
  if method=='GET' and path=='/trades/5501':return tv.Resp(200,[])
  raise AssertionError('Unexpected fake call '+method+' '+path)
 s=tv.fresh(lagging_trades)
 status=ba.check_order_status('5501',sess=s)
 check('Dhan order-book confirmed fills survive a lagging trade book',status['filled_qty']==3,{'broker_filledQty':3,'adapter_filled_qty':status['filled_qty']})
 import sip
 oldmark=sip.mark_rejected
 sip.mark_rejected=lambda oid:None
 stored={'sp':pd.DataFrame([dict(symbol='ABC',swing_qty=10,investing_qty=0,momentum_qty=0,entry_price=100.,entry_date='2026-09-30',strategy='W+TT',mode='LIVE',product='CNC',order_id='5501',note='AMO pending')])}
 oldread,oldwrite=at.read_split,at.write_split
 at.read_split=lambda:stored['sp'].copy()
 at.write_split=lambda d:stored.__setitem__('sp',d.copy())
 at.sync(s)
 check('Cancelled partially filled BUY retains its 3 actual shares',int(stored['sp'].iloc[0].swing_qty)==3,{'stored_qty':int(stored['sp'].iloc[0].swing_qty)})
 at.read_split,at.write_split=oldread,oldwrite
 sip.mark_rejected=oldmark

 # 5: Journal created at the first partial fill must expand with later BUY fills.
 import journal as j
 r=dict(symbol='ABC',swing_qty=3,investing_qty=0,momentum_qty=0,entry_price=101.,entry_date='2026-09-30',strategy='W+TT',mode='LIVE',product='CNC',order_id='5501',note='AMO pending')
 stored={'journal':pd.DataFrame([j._new_row(r,'DHAN',3,True)])}
 oldload,oldsave,olddiv=j.load,j.save,j.dividends_of
 j.load=lambda:stored['journal'].copy()
 j.save=lambda d:stored.__setitem__('journal',d.copy())
 j.dividends_of=lambda sym:[]
 r['swing_qty']=6
 out,_=j.sync(pd.DataFrame([r]),[dict(symbol='ABC',qty=6)],{},dict(ABC=101.),today='2026-09-30',quiet=True)
 q=sum(float(v) for v in out.loc[out.status=='OPEN','qty'])
 check('Journal quantity follows later cumulative BUY fills 3 to 6',q==6,{'split_qty':6,'demat_qty':6,'journal_qty':q})
 j.load,j.save,j.dividends_of=oldload,oldsave,olddiv

 print('\n%d/%d independent safety expectations passed'%(sum(ok for _,ok in RESULTS),len(RESULTS)),flush=True)
 sys.exit(0 if all(ok for _,ok in RESULTS) else 1)
if __name__=='__main__':main()
