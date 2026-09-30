#!/usr/bin/env python3
"""
SUPER-BUY BACKTEST  --  W+TT signal AND momentum top 20 on the same day (30 Sep 2026)
===================================================================================

RB: "Super-Buy = in BOTH the W+TT Swing list and the Momentum top 20 -- isse
backtest karo." Same honest setup as strategy_lab.py (>= Rs 10k Cr point in
time, Rs 5 Cr turnover, Rs 2 lakh, Dhan costs + 0.10% slippage, tax, idle
cash 6%, 2013-19 AND 2020-26 judged separately).

PRE-REGISTERED (fixed before running)
  Super-Buy signal : W+TT signal day (Weinstein + Trend Template, exactly the
                     screener) AND that stock's RAMOM rank <= 20 on the same
                     day (live score, among eligible stocks, raw rank).
                     Buy at the next open.
  Exits tested     : INV   W+TT investing exit (10 closes < falling 30w MA)
                     SWING W+TT swing exit (20% stop / close < 40w MA)
                     MOM   momentum exit: on a month's 1st trading day the
                           rank is > 40 -> sell at that open
  Compared with    : all W+TT signals (same exits), RAMOM top 20 (live).
  Portfolios       : 10 and 20 slots, RS-ranked, idle cash 6%.

python3 superbuy_backtest.py     (~10 min, cached price files)
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
import daily_screener as ds                                    # noqa: E402
import fusion_backtest as fb                                   # noqa: E402
import strategy_lab as sl                                      # noqa: E402
from fusion_backtest import START, SPLIT, periods              # noqa: E402


def mom_exit(P, S, cal):
    """Flag the close BEFORE a month's 1st trading day when the rank on that
    close is > 40 (or unranked) -> simulate_exit sells at the rebalance-day
    open, exactly like the live monthly rebalance."""
    rank = S.rank(axis=1, ascending=False)
    k0 = cal.searchsorted(pd.Timestamp(START)) - 30
    reb = sl.rebal_days(cal, max(k0, 1), len(cal), "M")
    flag = pd.DataFrame(False, index=cal, columns=S.columns)
    idx = [k - 1 for k in sorted(reb) if k >= 1]
    r = rank.iloc[idx]
    flag.iloc[idx] = ((r > 40) | r.isna()).values
    return flag


def trades_table(t, cal, name, rows):
    if t is None or t.empty:
        rows.append({"strategy": name, "trades": 0})
        return
    is_ = cal[t.k_in.values] < pd.Timestamp(SPLIT)
    r = {"strategy": name}
    for tag, m in (("13-19", is_), ("20-26", ~is_), ("ALL", None)):
        s = fb.trade_stats(t if m is None else t[m])
        if tag == "ALL":
            r.update({"trades": s.get("trades"), "win%": s.get("win%"),
                      "avg%": s.get("avg%"), "median%": s.get("median%"),
                      "PF": s.get("PF"), "hold d": s.get("hold_days")})
        else:
            r["avg% " + tag] = s.get("avg%")
            r["n " + tag] = s.get("trades")
    rows.append(r)


def main():
    P, uni = fb.load_pit10k()
    cal = P["Close"].index
    I = fb.indicators(P)
    elig = (uni & I["liq"]).fillna(False)
    S, ok = sl.scores(P, elig)
    mrank = S["RAMOM"].rank(axis=1, ascending=False)
    sig, rsw, m150, m200 = bt.signals(P, uni)
    sb = (sig & (mrank <= 20)).fillna(False)
    print("Signals: W+TT %d | Super-Buy %d" % (int(sig.values.sum()),
                                               int(sb.values.sum())))
    mx = mom_exit(P, S["RAMOM"], cal)

    def wtt_trades(entry, overlap):
        t = bt.simulate(P, entry, rsw, m150, m200, START, overlap=overlap)
        if t.empty:
            return t, t
        inv = t.drop(columns=["k_out", "exit", "ret", "bars"]).rename(
            columns={"k_iout": "k_out", "inv_exit": "exit"})
        inv["ret"] = inv["exit"] / inv["entry"] - 1
        inv["bars"] = inv["k_out"] - inv["k_in"]
        sw = t.copy()
        sw["ret"] = sw["exit"] / sw["entry"] - 1
        return inv, sw

    rows_t, rows_p = [], []
    cands = {}
    for name, ent in (("SUPER-BUY", sb), ("ALL W+TT", sig)):
        inv1, sw1 = wtt_trades(ent, False)
        invc, swc = wtt_trades(ent, True)
        mo1 = fb.simulate_exit(P, ent, mx, rsw, START, overlap=False)
        moc = fb.simulate_exit(P, ent, mx, rsw, START, overlap=True)
        for ex, t1, tc in (("INV", inv1, invc), ("SWING", sw1, swc),
                           ("MOM", mo1, moc)):
            trades_table(t1, cal, "%s | %s exit" % (name, ex), rows_t)
            cands["%s | %s exit" % (name, ex)] = tc
    cols = ["col", "k_sig", "k_in", "k_out", "entry", "exit", "rs"]
    for key, tc in cands.items():
        for slots in (10, 20):
            r = {"strategy": "%s | %d slots" % (key, slots)}
            if tc is None or tc.empty:
                rows_p.append(r)
                continue
            c = tc[cols]
            for tag, a, b in periods(cal):
                pre, tr, _ = fb.run_cash(P, c, slots, a, b, tax=False)
                post, _, _ = fb.run_cash(P, c, slots, a, b, tax=True)
                sl._fill(r, tag, pre, post, tr, cal)
            rows_p.append(r)
        print("  done: " + key, flush=True)
    ind = pd.read_csv(os.path.join(ds.DATA, "_nse_industry.csv"))
    m = dict(zip(ind.Symbol.astype(str).str.lower(), ind.Industry))
    sector = np.array([m.get(c, "?") for c in P["Close"].columns],
                      dtype=object)
    r = {"strategy": "BASE RAMOM top20 + sector cap (live)"}
    for tag, a, b in periods(cal):
        pre, tr = sl.run_rank(P, S["RAMOM"], 20, a, b, "M", tax=False,
                              sector=sector, sector_cap=4)
        post, _ = sl.run_rank(P, S["RAMOM"], 20, a, b, "M", tax=True,
                              sector=sector, sector_cap=4)
        sl._fill(r, tag, pre, post, tr, cal)
    rows_p.append(r)
    r = {"strategy": "NIFTY 50 buy & hold"}
    for tag, a, b in periods(cal):
        sl._fill(r, tag, fb.nifty_curve(P, a, b, tax=False),
                 fb.nifty_curve(P, a, b, tax=True), 1, cal)
    rows_p.append(r)

    pd.set_option("display.width", 250)
    f = lambda x: "%.1f" % x                                   # noqa: E731
    print("\n" + "=" * 110 + "\n TRADES (one open trade per stock, ~0.5% "
          "round trip)\n" + "=" * 110)
    print(pd.DataFrame(rows_t).set_index("strategy").to_string(
        float_format=f))
    print("\n" + "=" * 110 + "\n PORTFOLIO -- Rs 2 lakh, Dhan costs + "
          "slippage, tax, idle cash 6% (CAGR %)\n" + "=" * 110)
    d = pd.DataFrame(rows_p).set_index("strategy")
    print(d.to_string(float_format=f))
    d.to_csv(os.path.join(ds.DATA, "superbuy_backtest.csv"))


if __name__ == "__main__":
    main()
