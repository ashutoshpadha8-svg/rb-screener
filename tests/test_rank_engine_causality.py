"""Deterministic causal/funding regressions. Pure AST extraction, no network,
credentials, broker imports, accounts or real orders. Run directly with Python.
"""
import ast
import copy
import math
import unittest
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
G=dict(np=np,pd=pd,copy=copy,math=math,CAPITAL=10000.,CASH_RATE=0.,CASH_BUY=0.,
       CASH_SELL=0.,CASH_SLIP=0.,DP_CHARGE=0.,STCG=.208,LTCG=.13,LTCG_FREE=125000.,SLAB=.312,
       FIXED_SLOT='fixed_Rs10000_live_default',NAV_DIV_SLOTS='reinvest_NAV_div_20',DEFAULT_MODE='fixed_Rs10000_live_default')
def pure(file,names):
    nodes=[x for x in ast.parse((ROOT/file).read_text()).body if isinstance(x,(ast.FunctionDef,ast.ClassDef)) and x.name in names]
    exec(compile(ast.Module(body=nodes,type_ignores=[]),file,'exec'),G)
pure('position_sizing.py',{'slot_budget','whole_shares'})
pure('fusion_backtest.py',{'TaxBook','_fy_end'})
pure('strategy_lab.py',{'run_rank','rebal_days'})

def run(o,h,l,c,score=None,**kw):
    dates=pd.bdate_range('2026-01-05',periods=len(o))
    P={k:pd.DataFrame({'TOY':v},index=dates) for k,v in zip(['Open','High','Low','Close'],[o,h,l,c])}
    S=pd.DataFrame({'TOY':score if score is not None else [1.]*len(o)},index=dates)
    log=[];stats={}
    e,tr=G['run_rank'](P,S,N=1,start_k=1,freq='D',capital=10000.,tax=False,cash_rate=0.,trade_log=log,stats=stats,**kw)
    return float(e.iloc[-1]),log,stats

class Timeline(unittest.TestCase):
    def test_intraday_stop_cannot_fund_past_open(self):
        value,log,_=run([100,100,100,120],[100,101,105,121],[100,99,89,119],[100,100,95,120],stop_pct=.1)
        self.assertEqual(value,9000.)
        day=[r for r in log if r['date'].startswith('2026-01-07')]
        self.assertEqual([r['side'] for r in day],['SELL'])
        self.assertEqual(day[0]['phase'],'INTRADAY')
    def test_intraday_target_cannot_fund_past_open(self):
        value,log,_=run([100,100,100,125],[100,101,125,126],[100,99,99,124],[100,100,125,125],target=.25)
        self.assertEqual(value,12500.)
        self.assertEqual(sum(r['side']=='BUY' and r['date'].startswith('2026-01-07') for r in log),0)
    def test_entry_day_stop_active(self):
        value,log,_=run([100,100,80,80],[100,101,81,81],[100,80,79,79],[100,85,80,80],stop_pct=.1)
        self.assertEqual(value,9000.)
        self.assertEqual(log[1]['phase'],'INTRADAY');self.assertEqual(log[1]['price'],90.)
    def test_entry_day_target_active(self):
        value,log,_=run([100,100,100,100],[100,130,101,101],[100,99,99,99],[100,120,100,100],target=.25)
        self.assertEqual(value,12500.)
        self.assertEqual(log[1]['reason'],'target');self.assertEqual(log[1]['price'],125.)
    def test_gap_target_precedes_later_stop(self):
        value,log,_=run([100,100,130],[100,101,132],[100,99,85],[100,100,90],score=[1,np.nan,np.nan],stop_pct=.1,target=.25)
        self.assertEqual(value,13000.)
        self.assertEqual(log[1]['phase'],'OPEN');self.assertEqual(log[1]['reason'],'target')
    def test_missing_open_defers_rank_sell(self):
        value,log,stats=run([100,100,np.nan,80],[100,101,np.nan,81],[100,99,np.nan,79],[100,100,np.nan,80],score=[1,np.nan,np.nan,np.nan])
        self.assertEqual(value,8000.)
        self.assertEqual(stats['deferred_missing_open'],1)
        self.assertTrue(log[1]['date'].startswith('2026-01-08'))
    def test_missing_final_close_never_fakes_liquidation(self):
        value,log,stats=run([100,100,np.nan],[100,101,np.nan],[100,99,np.nan],[100,100,np.nan])
        self.assertEqual(value,10000.)
        self.assertEqual(stats['unliquidated_positions'],1)
        self.assertEqual(sum(x['side']=='SELL' for x in log),0)
    def test_gap_stop_fills_at_lower_open(self):
        value,log,_=run([100,100,70],[100,101,80],[100,99,60],[100,100,75],stop_pct=.1)
        self.assertEqual(value,7000.);self.assertEqual(log[1]['price'],70.)
    def test_ambiguous_intraday_touches_use_stop_first(self):
        value,log,stats=run([100,100,100],[100,101,130],[100,99,85],[100,100,110],stop_pct=.1,target=.25)
        self.assertEqual(value,9000.);self.assertEqual(stats['ambiguous_intraday_bars'],1)
    def test_trailing_update_not_retroactive(self):
        value,log,_=run([100,100,120],[100,130,121],[100,95,119],[100,120,120],trail_pct=.1)
        self.assertEqual(value,12000.)
        self.assertEqual(log[-1]['reason'],'window_end')
    def test_stale_prior_close_blocks_new_buy(self):
        value,log,_=run([100,100,100],[100,101,101],[100,99,99],[100,np.nan,100],score=[np.nan,1,1])
        self.assertEqual(value,10000.);self.assertEqual(log,[])
    def test_plain_buy_hold_control(self):
        value,_,_=run([100,100,110,120],[100,101,111,121],[100,99,109,119],[100,100,110,120])
        self.assertEqual(value,12000.)
    def test_invalid_stop_target_inputs(self):
        for kw in [{'stop_pct':1},{'stop_pct':-.1},{'trail_pct':float('nan')},{'target':0},{'buy_delay':.5},{'trail_atr':2},{'buy_within':-5},{'sector_cap':4},{'buffer':float('nan')},{'breakeven':-.1}]:
            with self.subTest(kw=kw),self.assertRaises(ValueError):run([100,100],[100,100],[100,100],[100,100],**kw)
    def test_future_price_mutation_never_changes_past_events(self):
        rng=np.random.default_rng(61)
        c=100*np.exp(np.cumsum(rng.normal(0,.03,30)));o=np.r_[100,c[:-1]]
        h=np.maximum(c,o)*1.06;l=np.minimum(c,o)*.94
        _,before,_=run(o,h,l,c,stop_pct=.1,trail_pct=.12,target=.25)
        altered=[x.copy() for x in [o,h,l,c]]
        for x in altered:x[20:]*=3
        _,after,_=run(*altered,stop_pct=.1,trail_pct=.12,target=.25)
        cutoff=pd.bdate_range('2026-01-05',periods=30)[20].isoformat()
        self.assertEqual([x for x in before if x['date']<cutoff],[x for x in after if x['date']<cutoff])
    def test_random_paths_never_backdate_cash_or_breach_funding(self):
        rng=np.random.default_rng(6)
        for _ in range(30):
            c=100*np.exp(np.cumsum(rng.normal(0,.035,35)));o=np.r_[100,c[:-1]]
            h=np.maximum(c,o)*1.04;l=np.minimum(c,o)*.96
            _,log,_=run(o,h,l,c,stop_pct=.1,target=.2)
            by={}
            for row in log:
                self.assertGreaterEqual(row['cash_after'],-1e-8)
                by.setdefault(row['date'],[]).append(row)
            for rows in by.values():
                phases=[{'OPEN':0,'INTRADAY':1,'CLOSE':2}[x['phase']] for x in rows]
                self.assertEqual(phases,sorted(phases))

class DailyRules(unittest.TestCase):
    def panel(self, scores, price=100.):
        scores=np.asarray(scores,dtype=float)
        dates=pd.bdate_range('2026-01-05',periods=len(scores))
        names=['A%02d'%i for i in range(scores.shape[1])]
        S=pd.DataFrame(scores,index=dates,columns=names)
        P={k:pd.DataFrame(price,index=dates,columns=names) for k in ['Open','High','Low','Close']}
        return P,S
    def execute(self,P,S,**kw):
        log=[];stats={}
        eq,_=G['run_rank'](P,S,N=20,start_k=1,capital=20000.,tax=False,cash_rate=0.,buffer=2,buy_within=5,max_positions=0,trade_log=log,stats=stats,**kw)
        return eq,log,stats
    def test_hold_rank40_sell_rank41_daily(self):
        a=np.tile(np.arange(41,0,-1,dtype=float),(4,1))
        a[1,0]=1.5 # rank40
        a[2,0]=.5 # rank41
        P,S=self.panel(a);_,log,_=self.execute(P,S,freq='D')
        exits=[x for x in log if x['symbol']=='A00' and x['side']=='SELL']
        self.assertEqual(len(exits),1);self.assertTrue(exits[0]['date'].startswith('2026-01-08'))
        self.assertEqual(exits[0]['reason'],'rank_or_regime')
    def test_daily_additions_keep_old_stocks_until_cash_exhausted(self):
        a=np.tile(np.arange(25,0,-1,dtype=float),(7,1))
        for day in range(1,6):
            a[day]=np.arange(25,0,-1,dtype=float)
            a[day,(day*5)%25:(day*5)%25+5]+=100
        P,S=self.panel(a);_,log,_=self.execute(P,S,freq='D')
        buys=[x for x in log if x['side']=='BUY']
        self.assertEqual(len(buys),20);self.assertEqual(len({x['symbol'] for x in buys}),20)
        self.assertEqual(sum(x['side']=='SELL' and x['reason']!='window_end' for x in log),0)
        self.assertGreaterEqual(min(x['cash_after'] for x in log),0.)
        self.assertEqual(sum(x['side']=='BUY' and x['date'].startswith('2026-01-12') for x in log),0)
    def test_held_top5_are_not_topped_up(self):
        P,S=self.panel(np.tile(np.arange(8,0,-1),(5,1)))
        _,log,_=self.execute(P,S,freq='D')
        self.assertEqual(sum(x['side']=='BUY' for x in log),5)
    def test_delay_refreshes_candidate_not_stale_plan(self):
        P,S=self.panel([[2,1],[1,2],[1,2],[1,2]])
        log=[]
        G['run_rank'](P,S,N=20,start_k=1,freq='D',buffer=2,buy_within=1,max_positions=0,buy_delay=1,capital=20000,tax=False,cash_rate=0,trade_log=log)
        buys=[x for x in log if x['side']=='BUY']
        self.assertEqual(len(buys),1);self.assertEqual(buys[0]['symbol'],'A01')
        self.assertTrue(buys[0]['date'].startswith('2026-01-07'))
    def test_daily_delay_never_spends_same_open_sale_proceeds(self):
        P,S=self.panel([[2,1],[2,1],[1,2],[1,2],[1,2]])
        log=[]
        G['run_rank'](P,S,N=1,start_k=1,freq='D',buffer=1,buy_within=1,max_positions=0,buy_delay=1,capital=10000,tax=False,cash_rate=0,trade_log=log)
        buys=[x for x in log if x['side']=='BUY']
        self.assertEqual([x['symbol'] for x in buys],['A00','A01'])
        self.assertTrue(buys[0]['date'].startswith('2026-01-07'))
        self.assertTrue(buys[1]['date'].startswith('2026-01-09'))
        self.assertFalse(any(x['side']=='BUY' and x['date'].startswith('2026-01-08') for x in log))
    def test_weekly_buys_can_have_daily_exits(self):
        a=np.tile(np.arange(41,0,-1,dtype=float),(10,1));a[1:,0]=.5
        P,S=self.panel(a);_,log,_=self.execute(P,S,freq='W',exit_freq='D')
        exit=next(x for x in log if x['symbol']=='A00' and x['side']=='SELL')
        self.assertTrue(exit['date'].startswith('2026-01-07'))
    def test_nonzero_costs_still_never_borrow(self):
        P,S=self.panel(np.tile(np.arange(25,0,-1),(6,1)))
        saved={k:G[k] for k in ['CASH_BUY','CASH_SELL','CASH_SLIP','DP_CHARGE']}
        try:
            G.update(CASH_BUY=.0012,CASH_SELL=.0011,CASH_SLIP=.001,DP_CHARGE=14.75)
            _,log,_=self.execute(P,S,freq='D')
            self.assertTrue(all(x['cash_after']>=0 for x in log))
            self.assertTrue(all(x['shares']==9 for x in log if x['side']=='BUY'))
        finally:G.update(saved)

class LossCarry(unittest.TestCase):
    def test_both_losses_keep_identity(self):
        b=G['TaxBook'](False);b.add(-100000,30);b.add(-100000,400);self.assertEqual(b.settle(),0)
        self.assertEqual((b.cf_st,b.cf_lt),(100000,100000));b.add(200000,30)
        self.assertAlmostEqual(b.settle(),20800.)
        self.assertEqual(b.cf_lt,100000.)
    def test_st_loss_offsets_positive_lt_only(self):
        b=G['TaxBook'](False);b.add(-100000,30);b.add(60000,400);self.assertEqual(b.settle(),0.)
        self.assertEqual((b.cf_st,b.cf_lt),(40000,0.))
    def test_lt_loss_cannot_offset_st_gain(self):
        b=G['TaxBook'](False);b.add(100000,30);b.add(-100000,400)
        self.assertEqual(b.settle(),20800.);self.assertEqual(b.cf_lt,100000.)
    def test_loss_reserve_nonmutating(self):
        b=G['TaxBook'](False);b.add(-100000,30);b.add(-100000,400)
        original=copy.deepcopy(b.__dict__);self.assertEqual(b.due(),0.);self.assertEqual(b.__dict__,original)
    def test_use_lt_carry_before_consuming_flexible_st(self):
        b=G['TaxBook'](False);b.cf_st=50000;b.cf_lt=40000;b.add(50000,400);b.settle()
        self.assertEqual((b.cf_st,b.cf_lt),(40000.,0.))

if __name__=='__main__':unittest.main(verbosity=2)
