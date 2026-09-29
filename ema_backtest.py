#!/usr/bin/env python3
"""
EMA 9/21 CROSS BACKTEST  --  RB's question (29 Sep 2026)
=======================================================

"9/21 EMA cross ka result kya hai jab upar cross ho to buy -- aur kuch
combinations check karo jo sabse accurate stocks dhoondhe."

Same honest setup as strategy_lab.py / fusion_backtest.py: >= Rs 10,000 Cr
point-in-time universe, 60-day median turnover > Rs 5 Cr, Rs 2 lakh start,
real Dhan costs + 0.10% slippage, Indian tax, idle cash 6%, 2013-01..2026-09,
judged in 2013-19 AND 2020-26 separately.

PRE-REGISTERED (fixed before running, no tuning afterwards)
  Signal  : EMA(9) of close crosses ABOVE EMA(21) today (was <= yesterday)
            -> buy at the next open.
  Filters : F0 plain cross
            F1 + close > 200-DMA
            F2 + RS rank >= 70 (6-month return vs Nifty, percentile)
            F3 + close > 200-DMA, 200-DMA rising (22 bars), RS >= 70
            F4 + Minervini Trend Template (the screener's TT)
            F5 + momentum rank top 40 (RAMOM, the momentum screener score)
            F6 + Trend Template + volume > 1.5x 50-day average
  Exits   : X1 EMA(9) crosses back BELOW EMA(21) -> next open
            X2 close below the 50-DMA -> next open
  = 14 variants. Baselines: W+TT (investing exit) and RAMOM top 20.

  "Accurate" is measured three ways, because win% alone lies:
    trades  win %, avg %, median %, profit factor (after ~0.5% round trip)
    finding % of trades that beat the equal-weight universe over the SAME
            days (did it pick better stocks, or just ride the market?)
    money   20-slot portfolio (RS-ranked), post-tax CAGR, max drawdown

python3 ema_backtest.py          (~5-10 min; downloads history once)
"""

import warnings
warnings.filterwarnings("ignore")

import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest as bt                                          # noqa: E402
import fusion_backtest as fb                                   # noqa: E402
import strategy_lab as sl                                      # noqa: E402
from fusion_backtest import START, SPLIT, perf, periods        # noqa: E402

SLOTS = 20


def build(P, uni):
    I = fb.indicators(P)
    C = I["C"]
    V = P["Volume"]
    elig = (uni & I["liq"]).fillna(False)
    e9, e21 = fb.ema(C, 9), fb.ema(C, 21)
    up = (e9 > e21) & (e9.shift(1) <= e21.shift(1))
    down = e9 < e21
    ma50 = C.rolling(50).mean()
    ma150 = C.rolling(150).mean()
    ma200 = C.rolling(200).mean()
    hi52, lo52 = C.rolling(252).max(), C.rolling(252).min()
    rs = fb.rs_rank(P, uni)
    tt = ((C > ma50) & (ma50 > ma150) & (ma150 > ma200) &
          (ma200 > ma200.shift(22)) & (C > 1.3 * lo52) &
          (C > 0.75 * hi52) & (rs >= 70))
    S, ok = sl.scores(P, elig)
    mrank = S["RAMOM"].rank(axis=1, ascending=False)
    vol15 = V > 1.5 * V.rolling(50).mean()
    base = up & elig
    F = {
        "F0 plain cross": base,
        "F1 + close>200DMA": base & (C > ma200),
        "F2 + RS>=70": base & (rs >= 70),
        "F3 + 200DMA up + RS>=70": base & (C > ma200) &
        (ma200 > ma200.shift(22)) & (rs >= 70),
        "F4 + Trend Template": base & tt,
        "F5 + momentum top40": base & (mrank <= 40),
        "F6 + TT + volume 1.5x": base & tt & vol15,
    }
    X = {"X1 EMA cross down": down, "X2 close<50DMA": C < ma50}
    F = {k: v.fillna(False).astype(bool) for k, v in F.items()}
    X = {k: v.fillna(False).astype(bool) for k, v in X.items()}
    return F, X, rs, ok, S


def split_stats(t, cal):
    out = {}
    if t.empty:
        return out
    is_ = cal[t.k_in.values] < pd.Timestamp(SPLIT)
    for tag, m in (("13-19", is_), ("20-26", ~is_), ("ALL", None)):
        s = fb.trade_stats(t if m is None else t[m])
        if tag == "ALL":
            out.update({"trades": s.get("trades"), "win%": s.get("win%"),
                        "avg%": s.get("avg%"), "median%": s.get("median%"),
                        "PF": s.get("PF"), "hold d": s.get("hold_days")})
        else:
            out["win% " + tag] = s.get("win%")
            out["avg% " + tag] = s.get("avg%")
    return out


def main():
    P, uni = fb.load_pit10k()
    cal = P["Close"].index
    F, X, rs, ok, S = build(P, uni)
    ew = sl.ew_index(P, ok)
    k0 = cal.searchsorted(pd.Timestamp(START))
    rows_t, rows_p = [], []

    def add(name, trades_df, cands):
        r = {"strategy": name}
        r.update(split_stats(trades_df, cal))
        ex = sl.excess_trades(trades_df, ew, cal)
        if len(ex):
            r["beat univ %"] = 100 * (ex.excess > 0).mean()
            r["avg excess %"] = 100 * ex.excess.mean()
        rows_t.append(r)
        p = {"strategy": name}
        for tag, a, b in periods(cal):
            pre, tr, _ = fb.run_cash(P, cands, SLOTS, a, b, tax=False)
            post, _, _ = fb.run_cash(P, cands, SLOTS, a, b, tax=True)
            sl._fill(p, tag, pre, post, tr, cal)
        rows_p.append(p)
        print("  done: " + name)

    print("\nRunning %d EMA variants + 2 baselines ..." % (len(F) * len(X)))
    for fn, ent in F.items():
        for xn, ext in X.items():
            name = "%s | %s" % (fn, xn)
            t1 = fb.simulate_exit(P, ent, ext, rs, START, overlap=False)
            tc = fb.simulate_exit(P, ent, ext, rs, START, overlap=True)
            add(name, t1, tc[["col", "k_sig", "k_in", "k_out", "entry",
                              "exit", "rs"]] if len(tc) else tc)

    # baselines
    sig, rsw, m150, m200 = bt.signals(P, uni)
    w1 = bt.simulate(P, sig, rsw, m150, m200, START, overlap=False)
    wc = bt.simulate(P, sig, rsw, m150, m200, START, overlap=True)
    ren = {"k_iout": "k_out", "inv_exit": "exit"}
    w1i = w1.drop(columns=["k_out", "exit", "ret", "bars"]).rename(
        columns=ren)
    w1i["ret"] = w1i["exit"] / w1i["entry"] - 1
    w1i["bars"] = w1i["k_out"] - w1i["k_in"]
    add("BASE W+TT investing exit", w1i,
        wc[["col", "k_sig", "k_in", "k_iout", "entry", "inv_exit", "rs"]]
        .rename(columns=ren))
    r = {"strategy": "BASE RAMOM top20 monthly"}
    for tag, a, b in periods(cal):
        pre, tr = sl.run_rank(P, S["RAMOM"], 20, a, b, "M", tax=False)
        post, _ = sl.run_rank(P, S["RAMOM"], 20, a, b, "M", tax=True)
        sl._fill(r, tag, pre, post, tr, cal)
    rows_p.append(r)
    r = {"strategy": "NIFTY 50 buy & hold"}
    for tag, a, b in periods(cal):
        sl._fill(r, tag, fb.nifty_curve(P, a, b, tax=False),
                 fb.nifty_curve(P, a, b, tax=True), 1, cal)
    rows_p.append(r)

    pd.set_option("display.width", 250)
    f = lambda x: "%.1f" % x                                   # noqa: E731
    print("\n" + "=" * 110)
    print(" TRADES (one open trade per stock, ~0.5% round-trip cost)")
    print("=" * 110)
    dt_ = pd.DataFrame(rows_t).set_index("strategy")
    print(dt_.to_string(float_format=f))
    print("\n" + "=" * 110)
    print(" PORTFOLIO -- %d slots, RS-ranked, Rs 2 lakh, Dhan costs + "
          "slippage, tax, idle cash 6%% (CAGR %%)" % SLOTS)
    print("=" * 110)
    dp = pd.DataFrame(rows_p).set_index("strategy")
    print(dp.to_string(float_format=f))
    out = os.path.join(bt.ds.DATA, "ema_backtest.csv")
    dt_.join(dp, how="outer", rsuffix="_p").to_csv(out)
    print("\nSaved: %s" % out)
    print("16 variants tested -> the best one is partly luck. Trust only what "
          "wins in BOTH halves.")


if __name__ == "__main__":
    main()
