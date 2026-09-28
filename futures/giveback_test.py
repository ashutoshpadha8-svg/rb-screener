# Usage: python3 giveback_test.py data/usatechidxusd-m1-bid-2016-01-01-2026-09-26.csv
# Test RB's idea on NOISE entries: once open profit >= ACT dollars, exit if it gives back GB% of peak open profit.
import sys, numpy as np, pandas as pd
sys.path.insert(0,'.')
import backtest as bt, tune_noise as tn
PV, BUDGET = 2.0, 1600.0
days = bt.day_table(bt.load(sys.argv[1]))
dates=[d['date'] for d in days]
d_is=[d for d in dates if d<=pd.Timestamp(bt.IS_END)]; d_oos=[d for d in dates if d>pd.Timestamp(bt.IS_END)]

def run(act, gb, target):
    out=[]; moves=[]; ranges=[]
    for day in days:
        o=day['o'][0]
        if len(moves)>=14 and not np.isnan(day['prev_close']):
            sigma=np.mean(moves[-14:],axis=0); ar=np.mean(ranges[-14:])
            n=max(1,min(50,int(BUDGET/(ar*PV))))
            ub=max(o,day['prev_close'])*(1+sigma); lb=min(o,day['prev_close'])*(1-sigma); vw=bt.vwap_proxy(day)
            pos=0; entry=0; i_in=0; peak=0.0
            for i in range(30,390):
                if pos!=0 and i>i_in:
                    # conservative: lock uses peak from PREVIOUS bars only; gap through lock fills at open
                    exit_px=None
                    if act and peak*PV*n>=act:
                        lock=entry+pos*peak*(1-gb)
                        if (pos>0 and day['l'][i]<=lock) or (pos<0 and day['h'][i]>=lock):
                            exit_px=min(lock,day['o'][i]) if pos>0 else max(lock,day['o'][i])
                    fav=pos*((day['h'][i] if pos>0 else day['l'][i])-entry)
                    if exit_px is None and target and fav*PV*n>=target: exit_px=entry+pos*target/(PV*n)
                    peak=max(peak,fav)
                    if exit_px is not None:
                        out.append(bt.trade(day['date'],pos,entry,exit_px,ar,bt.mae(day,pos,entry,i_in,i))); pos=0; continue
                if i%30==0:
                    c=day['c'][i-1]
                    if pos==1 and c<max(ub[i-1],vw[i-1]): out.append(bt.trade(day['date'],1,entry,c,ar,bt.mae(day,1,entry,i_in,i-1))); pos=0
                    elif pos==-1 and c>min(lb[i-1],vw[i-1]): out.append(bt.trade(day['date'],-1,entry,c,ar,bt.mae(day,-1,entry,i_in,i-1))); pos=0
                    if pos==0 and i<385:
                        if c>ub[i-1]: pos,entry,i_in,peak=1,c,i,0.0
                        elif c<lb[i-1]: pos,entry,i_in,peak=-1,c,i,0.0
            if pos!=0: out.append(bt.trade(day['date'],pos,entry,day['c'][-1],ar,bt.mae(day,pos,entry,i_in,389)))
        moves.append(np.abs(day['c']/o-1)); ranges.append(day['h'].max()-day['l'].min())
    bt.RISK_PER_TRADE=BUDGET; t=bt.to_dollars(out,PV,0.25)
    r={}
    for lab,part,dd in (('IS',t[t.date<=bt.IS_END],d_is),('OOS',t[t.date>bt.IS_END],d_oos)):
        s=bt.stats(part,'pnl'); c=bt.combine_sim(part,dd,60)
        r[lab]=(round(100*(part.pnl>0).mean()),round(s['avg$']),round(s['PF'],2),round(c['pass%'],1))
    return r
print('rule | IS: win%, avg$/trade, PF, pass% | OOS: same')
for name,a,g,tg in [('NOISE as tested (no lock)',0,0,0),('lock after +$100, exit on 10% giveback (RB idea)',100,0.10,0),
                    ('lock after +$300, exit on 30% giveback',300,0.30,0),('lock after +$500, exit on 50% giveback',500,0.50,0),
                    ('fixed target +$500 (1% of 50K)',0,0,500)]:
    r=run(a,g,tg); print(name.ljust(50),'| IS',r['IS'],'| OOS',r['OOS'])
