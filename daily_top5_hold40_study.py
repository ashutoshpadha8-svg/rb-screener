#!/usr/bin/env python3
"""OFFLINE research: daily raw Top-5 additions, hold through rank 40.

Manual signals only; assumes every eligible signal is accepted and filled at
next-session open. No broker imports, token reads, downloads or real orders.
Use --data PATH to an existing public-price cache. Historical cap is estimated
from the current cap anchor; current survivors are NOT point-in-time membership.
Run: python3 daily_top5_hold40_study.py --data ./data --out ./reports/daily_hold40
"""
import argparse
import ast
import copy
import hashlib
import io
import json
import math
from pathlib import Path
import warnings
import zipfile
import numpy as np
import pandas as pd
warnings.filterwarnings('ignore', category=FutureWarning)
HERE=Path(__file__).resolve().parent

def engine():
    g=dict(np=np,pd=pd,math=math,copy=copy)
    constant_names={'CAPITAL','CASH_RATE','EXCH_EQ','EXCH_FUT','SEBI','GST','CASH_BUY','CASH_SELL','CASH_SLIP','DP_CHARGE','CESS','STCG','LTCG','LTCG_FREE','SLAB'}
    for file,names in [('position_sizing.py',{'slot_budget','whole_shares'}),('fusion_backtest.py',{'TaxBook','_fy_end'}),('strategy_lab.py',{'run_rank','rebal_days','scores','zrow'})]:
        nodes=[]
        for node in ast.parse((HERE/file).read_text()).body:
            if isinstance(node,(ast.FunctionDef,ast.ClassDef)) and node.name in names:nodes.append(node)
            elif isinstance(node,ast.Assign):
                targets={t.id for target in node.targets for t in ast.walk(target) if isinstance(t,ast.Name)}
                allowed=constant_names if file=='fusion_backtest.py' else {'FIXED_SLOT','NAV_DIV_SLOTS','DEFAULT_MODE'} if file=='position_sizing.py' else set()
                if targets <= allowed:nodes.append(node)
        exec(compile(ast.Module(body=nodes,type_ignores=[]),file,'exec'),g)
    return g

def load(data, keep_global_gaps=False):
    manifest={};bad=[]
    def read(path):
        manifest[path.relative_to(data).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
        f=pd.read_csv(path,parse_dates=['Date']).set_index('Date').sort_index()
        return f[~f.index.duplicated(keep='last')]
    bm=read(data/'nifty 50.csv')
    cap_path=data/'_nse_mcap_latest.csv';capframe=pd.read_csv(cap_path)
    manifest[cap_path.name]=hashlib.sha256(cap_path.read_bytes()).hexdigest()
    caps=dict(zip(capframe.symbol.str.upper(),capframe.mcap_cr));asof=pd.Timestamp(capframe['asof'].iloc[0])
    sec_path=data/'_nse_industry.csv';sectors={}
    if sec_path.exists():
        sec=pd.read_csv(sec_path);sectors=dict(zip(sec.Symbol.str.upper(),sec.Industry))
        manifest[sec_path.name]=hashlib.sha256(sec_path.read_bytes()).hexdigest()
    bhav={}
    for path in sorted((data/'_bhav').glob('*.zip')):
        with zipfile.ZipFile(path) as z:f=pd.read_csv(io.BytesIO(z.read(z.namelist()[0])))
        f=f[f.SctySrs.isin(['EQ','BE','BZ'])].sort_values('TtlTradgVol',ascending=False).drop_duplicates('TckrSymb')
        bhav[pd.Timestamp(f.TradDt.iloc[0])]=f.set_index('TckrSymb')
        manifest[path.relative_to(data).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    cal=bm.loc['2011-01-01':].index
    frames={};anchor={}
    for sym,cap in caps.items():
        if not np.isfinite(cap) or cap<1000:continue
        path=data/(sym.lower()+'.csv')
        if not path.exists():continue
        f=read(path)
        # The current capitalization must be divided by SAME-ASOF close.
        for date,tab in bhav.items():
            if sym in tab.index:
                r=tab.loc[sym]
                for k,v in [('Open','OpnPric'),('High','HghPric'),('Low','LwPric'),('Close','ClsPric'),('Volume','TtlTradgVol')]:f.loc[date,k]=float(r[v])
        if asof not in f.index or not np.isfinite(f.loc[asof,'Close']) or f.loc[asof,'Close']<=0:continue
        anchor[sym]=float(f.loc[asof,'Close'])
        f=f.reindex(cal).copy();keys=['Open','High','Low','Close','Volume']
        f[keys]=f[keys].apply(pd.to_numeric,errors='coerce')
        invalid=(f.High+1e-6<f[['Open','Low','Close']].max(axis=1))|(f.Low-1e-6>f[['Open','High','Close']].min(axis=1))|(f[keys[:4]]<=0).any(axis=1)
        if invalid.any():bad.append({'symbol':sym,'invalid_bars':int(invalid.sum())});f.loc[invalid,keys]=np.nan
        if f.Close.notna().sum()>=280:frames[sym]=f
    if len(frames)<50:raise ValueError('Insufficient cached stock histories: need at least 50')
    P={k:pd.DataFrame({s:f[k] for s,f in frames.items()},index=cal) for k in ['Open','High','Low','Close','Volume']}
    gap_dates=P['Close'].index[P['Close'].notna().sum(axis=1)==0]
    if not keep_global_gaps:
        P={k:v.drop(index=gap_dates) for k,v in P.items()};cal=P['Close'].index
    estimated=P['Close'].ffill(limit=5).div(pd.Series(anchor)).mul(pd.Series(caps))
    elig=(estimated>=10000)&((P['Close'].ffill(limit=5)*P['Volume']).rolling(60).median()>5e7)
    return P,elig,bm.reindex(cal),np.array([sectors.get(s,'?') for s in P['Close'].columns]),dict(cap_asof=str(asof.date()),loaded=len(frames),data_start=str(cal[0].date()),data_end=str(cal[-1].date()),bad_bars=bad,all_stock_gap_dates=[str(x.date()) for x in gap_dates],global_gaps_retained=keep_global_gaps,manifest=manifest)


def metrics(eq,capital):
    seed=pd.Series([capital],index=[eq.index[0]-pd.Timedelta(days=1)])
    curve=pd.concat([seed,eq]);dd=curve/curve.cummax()-1
    years=(eq.index[-1]-seed.index[0]).days/365.25
    monthly=curve.resample('ME').last()
    # Exclude the last partial calendar month, e.g. the cache ending Sep 25.
    if eq.index[-1] < eq.index[-1]+pd.offsets.MonthEnd(0):monthly=monthly.iloc[:-1]
    rolling=100*(monthly/monthly.shift(12)-1);rolling=rolling.dropna()
    return dict(final_nav=float(eq.iloc[-1]),cagr_pct=100*((eq.iloc[-1]/capital)**(1/years)-1),max_dd_pct=100*float(dd.min()),rolling12_n=len(rolling),rolling12_mean_pct=float(rolling.mean()),rolling12_median_pct=float(rolling.median()),rolling12_best_pct=float(rolling.max()),rolling12_worst_pct=float(rolling.min()),rolling12_positive_pct=float(100*(rolling>0).mean())),rolling


def diagnostics(log,P):
    oneprice=0;exposure=[];held={};peak=0;trades=pd.DataFrame(log)
    actions={'STAR':'2024-12-06','VEDL':'2026-04-30'}
    for row in log:
        dt=pd.Timestamp(row['date']);sym=row['symbol']
        if row['side']=='BUY':
            held[sym]=dt
            hi=P['High'].loc[dt,sym];lo=P['Low'].loc[dt,sym]
            if np.isfinite(hi) and hi==lo:oneprice+=1
            peak=max(peak,len(held))
        else:
            start=held.pop(sym,None)
            if start is not None and sym in actions and start<pd.Timestamp(actions[sym])<=dt:
                exposure.append(dict(symbol=sym,entry=str(start.date()),exit=str(dt.date()),action_date=actions[sym]))
    return dict(peak_positions=peak,one_price_entries=oneprice,known_demerger_exposures=exposure)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data',type=Path,default=HERE/'data');p.add_argument('--out',type=Path,default=HERE/'reports/daily_hold40')
    p.add_argument('--capital',type=float,default=200000.)
    p.add_argument('--keep-global-gaps',action='store_true',help='Diagnostic: retain all-stock missing dates; can manufacture eligibility exits')
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    if not np.isfinite(a.capital) or a.capital<=0:raise ValueError('capital must be positive')
    P,elig,bm,sector,meta=load(a.data,a.keep_global_gaps);g=engine();S=g['scores'](P,elig)[0]['RAMOM'];cal=P['Close'].index
    runs=[('daily_NAV20_sector4',g['NAV_DIV_SLOTS'],0,4,20),('daily_fixed20_sector4',g['FIXED_SLOT'],0,4,20),('daily_NAV20_sell_confirm_delay1',g['NAV_DIV_SLOTS'],1,4,20),('daily_NAV20_no_sector_cap',g['NAV_DIV_SLOTS'],0,None,20),('daily_NAV5_sector4',g['NAV_DIV_SLOTS'],0,4,5),('daily_fixed5_sector4',g['FIXED_SLOT'],0,4,5)]
    periods=[('FULL','2013-01-01',None),('2013_2019','2013-01-01','2020-01-01'),('2020_2026','2020-01-01',None)]
    rows=[];allroll=[];diags={}
    for label,mode,delay,cap,slots in runs:
        for period,start,end in periods:
            if period!='FULL' and label!='daily_NAV20_sector4':continue
            first=int(cal.searchsorted(pd.Timestamp(start)));last=len(cal) if end is None else int(cal.searchsorted(pd.Timestamp(end)))
            for tax in [False,True]:
                name=label+'_'+period+('_modeled_tax' if tax else '_before_tax');log=[];stats={}
                eq,nt=g['run_rank'](P,S,N=slots,start_k=first,end_k=last,freq='D',exit_freq='D',buffer=40/slots,buy_within=5,max_positions=0,capital=a.capital,tax=tax,cash_rate=0.,allocation_mode=mode,sector=sector if cap else None,sector_cap=cap,buy_delay=delay,stats=stats,trade_log=log)
                m,roll=metrics(eq,a.capital);diag=diagnostics(log,P);diags[name]=dict(stats=stats,**diag)
                rows.append(dict(name=name,period=period,tax_mode='modeled_current_rates' if tax else 'before_tax',capital=a.capital,sizing=mode,sizing_slots=slots,sector_cap=cap or 0,buy_delay=delay,sells=nt,peak_positions=diag['peak_positions'],one_price_entries=diag['one_price_entries'],known_demerger_exposures=len(diag['known_demerger_exposures']),**m))
                eq.rename('nav').to_csv(a.out/(name+'_nav.csv'));pd.DataFrame(log).to_csv(a.out/(name+'_trades.csv'),index=False)
                allroll.extend(dict(name=name,end_month=str(dt.date()),return_pct=float(v)) for dt,v in roll.items())
                print(name,'12m mean',round(m['rolling12_mean_pct'],2),'CAGR',round(m['cagr_pct'],2),'DD',round(m['max_dd_pct'],2),'CA',len(diag['known_demerger_exposures']),flush=True)
    first=cal.searchsorted(pd.Timestamp('2013-01-01'));idx=cal[first:]
    if np.isfinite(bm.Open.iloc[first]) and bm.Open.iloc[first]>0:
        eq=a.capital*bm.Close.iloc[first:]/bm.Open.iloc[first];m,roll=metrics(eq,a.capital)
        rows.append(dict(name='Nifty50_price_only_FULL',period='FULL',tax_mode='before_tax',capital=a.capital,sizing='buy_hold_price_index',sector_cap=0,buy_delay=0,sells=0,peak_positions=1,one_price_entries=0,known_demerger_exposures=0,**m))
        allroll.extend(dict(name='Nifty50_price_only_FULL',end_month=str(dt.date()),return_pct=float(v)) for dt,v in roll.items())
        eq.rename('nav').to_csv(a.out/'Nifty50_price_only_FULL_nav.csv')
    pd.DataFrame(rows).to_csv(a.out/'summary.csv',index=False);pd.DataFrame(allroll).to_csv(a.out/'rolling12.csv',index=False)
    meta.update(capital=a.capital,ranking='RAMOM exact strategy_lab.scores',check_frequency='daily prior-close signals; next-open fills',buys='raw ranks 1..5; no top-ups; skip if cash below engine minimum Rs1000; no new contributions',sells='rank >40 or no longer eligible; final close liquidation is evaluation only',daily_existing_positions='held through rank40, not replaced every day',cap_mix='not forced for raw Top5 research; prior 60/25/15 amount preference is a separate manual allocation choice',idle_cash_rate=0.,costs={k:float(g[k]) for k in ['CASH_BUY','CASH_SELL','CASH_SLIP','DP_CHARGE']},diagnostics=diags,limitations=['Default omits globally missing stock sessions (2022-05-11) from indicators and execution; that session cannot be independently evaluated','Current survivors and constant-share market-cap estimates are not point-in-time historical membership','Cap floor Rs10000 Cr verified only on estimated previous-close cap, not broker execution-time live cap','Cached prices and all corporate actions not independently validated; known demerger exposures invalidate economic-profit interpretation','Each modeled signal assumed accepted; unknown manual declines and delayed/missed/partial fills cannot be forecast','No order-book queue model; one-price entries may not fill','Current flat tax rates, annual carry and exemptions are simplified, no historical-rate or 8-year carry expiry reconstruction','Overlapping rolling12 windows are not independent and do not forecast the next12 months','Cash-only additions: capital/N sizing, no extra position-count ceiling; default current live monthly mode is unchanged'])
    (a.out/'metadata.json').write_text(json.dumps(meta,indent=2))
if __name__=='__main__':main()
