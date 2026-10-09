"""Nifty fill from NSE's daily index file (9 Oct: FREE Dhan plan -> Nifty 10 days stale -> RS NaN crash)."""
import datetime as dt,sys,unittest,io,contextlib
from pathlib import Path
from unittest.mock import patch
import pandas as pd,numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import broker_api as ba
def stale():
 idx=pd.bdate_range('2026-09-01','2026-09-25')
 return pd.DataFrame({'Open':1.0,'High':1.0,'Low':1.0,'Close':24000.0,'Volume':0},index=idx)
FAKE={dt.date(2026,9,28):(1,1,1,23900.0),dt.date(2026,10,8):(1,1,1,22231.8),dt.date(2026,10,9):(1,1,1,22520.45)}
class IndexFill(unittest.TestCase):
 def run_fill(self,table,want=dt.date(2026,10,9)):
  w=[]
  with patch.object(ba,'_index_day',lambda d,name='Nifty 50':table.get(d)),contextlib.redirect_stdout(io.StringIO()):
   return ba.index_fill(stale(),want,w),w
 def test_fills_missing_days_only(self):
  out,w=self.run_fill(FAKE)
  self.assertEqual(out.index[-1],pd.Timestamp('2026-10-09'));self.assertAlmostEqual(out.loc['2026-10-08','Close'],22231.8)
  self.assertEqual(len(out),len(stale())+3);self.assertEqual(list(out.columns),list(stale().columns));self.assertEqual(w,[])
 def test_nothing_published_keeps_frame(self):
  out,_=self.run_fill({});self.assertEqual(len(out),len(stale()))
 def test_absurd_jump_stops(self):
  out,w=self.run_fill({dt.date(2026,9,28):(1,1,1,5000.0)});self.assertEqual(len(out),len(stale()));self.assertTrue(w)
 def test_up_to_date_untouched(self):
  out,_=self.run_fill(FAKE,want=dt.date(2026,9,25));self.assertEqual(len(out),len(stale()))
 def test_ffill_gap_now_covered(self):
  # the crash: 10 sessions > ffill(limit=5) -> NaN benchmark on the last bar
  out,_=self.run_fill(FAKE);cal=pd.bdate_range('2026-09-01','2026-10-09')
  self.assertFalse(np.isnan(out['Close'].reindex(cal).ffill(limit=5).iloc[-1]))
  self.assertTrue(np.isnan(stale()['Close'].reindex(cal).ffill(limit=5).iloc[-1]))
if __name__=='__main__':unittest.main()
