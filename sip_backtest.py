#!/usr/bin/env python3
"""
SIP BACKTEST  --  plain SIP vs "buy on a drop" vs "buy on a rise"
=================================================================

RB's SIP idea (27 Sep 2026), tested BEFORE coding it. Pre-registered:

  Money      Rs 10,000 comes in on the 1st trading day of every month. Money not
             yet invested waits in cash at 6%/yr (fair to the waiting rules).
  Rules      SIP monthly   buy with all waiting cash on the 1st trading day
             SIP weekly    Rs 10,000 x 12/52 every week's first trading day
             SIP daily     Rs 10,000 x 12/252 every trading day
             DIP 5 / 10    buy with ALL waiting cash when the close is >= 5% /
                           10% below the last buy price (first buy = day 1)
             DIP52 10 / 20 buy with all waiting cash when the close is >= 10% /
                           20% below its 52-week high
             UP 5 / 10     buy with all waiting cash when the close is >= 5% /
                           10% above the last buy price
  Costs      Dhan delivery buy: STT 0.1% + stamp 0.015% + exchange/SEBI/GST
             + 0.10% slippage. Units are fractional (no rounding luck).
  Measure    XIRR (money-weighted return) on the money put in, value at the
             end incl. the cash still waiting. 2013-01..2026-09 and each half
             from zero (2013-19, 2020-26).
  Assets     NIFTY 50 index (as the ETF, price only: an ETF adds ~1.2%/yr
             dividends) and every b173 stock with data from 2013.
             !! b173 = today's big SURVIVORS: stocks that crashed and never
             came back are missing. That bias HELPS "buy on a drop" the most.

python3 sip_backtest.py
"""

import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import daily_screener as ds                                    # noqa: E402
import backtest as bt                                          # noqa: E402

BUDGET = 10000.0
CASH_RATE = 0.06
BUY_COST = 0.001 + 0.00015 + 0.0000307 * 1.18 + 0.000001 * 1.18 + 0.001
PERIODS = [("FULL 2013-26", "2013-01-01", "2026-09-30"),
           ("2013-19", "2013-01-01", "2019-12-31"),
           ("2020-26", "2020-01-01", "2026-09-30")]
RULES = ["SIP monthly", "SIP weekly", "SIP daily", "DIP 5", "DIP 10",
         "DIP52 10", "DIP52 20", "UP 5", "UP 10"]


def xirr(flows):
    """flows: [(Timestamp, amount)] -> annual rate (Newton + bisection)."""
    t0 = flows[0][0]
    yrs = np.array([(d - t0).days / 365.25 for d, _ in flows])
    amt = np.array([a for _, a in flows])
    f = lambda r: np.sum(amt / (1 + r) ** yrs)                     # noqa
    lo, hi = -0.99, 5.0
    if f(lo) * f(hi) > 0:
        return np.nan
    for _ in range(200):
        mid = (lo + hi) / 2
        if f(lo) * f(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def sim(px, rule, start, end):
    s = px[(px.index >= start) & (px.index <= end)].dropna()
    if len(s) < 250:
        return None
    hi52 = px.rolling(252, min_periods=120).max().reindex(s.index)
    day_rate = (1 + CASH_RATE) ** (1 / 252) - 1
    cash = units = 0.0
    last_buy = None
    flows = []
    prev = None
    idle = []
    for d, p in s.items():
        cash *= 1 + day_rate
        new_month = prev is None or d.month != prev.month
        new_week = prev is None or d.isocalendar()[1] != prev.isocalendar()[1]
        if new_month:
            cash += BUDGET
            flows.append((d, -BUDGET))
        spend = 0.0
        if rule == "SIP monthly":
            spend = cash if new_month else 0.0
        elif rule == "SIP weekly":
            spend = min(cash, BUDGET * 12 / 52) if new_week else 0.0
        elif rule == "SIP daily":
            spend = min(cash, BUDGET * 12 / 252)
        elif last_buy is None:
            spend = cash                                      # day 1
        elif rule.startswith("DIP52"):
            x = float(rule.split()[1]) / 100
            if hi52.loc[d] == hi52.loc[d] and p <= hi52.loc[d] * (1 - x):
                spend = cash
        elif rule.startswith("DIP"):
            x = float(rule.split()[1]) / 100
            if p <= last_buy * (1 - x):
                spend = cash
        elif rule.startswith("UP"):
            y = float(rule.split()[1]) / 100
            if p >= last_buy * (1 + y):
                spend = cash
        if spend > 1:
            units += spend * (1 - BUY_COST) / p
            cash -= spend
            last_buy = p
        idle.append(cash)
        prev = d
    value = units * float(s.iloc[-1]) + cash
    put = -sum(a for _, a in flows)
    flows.append((s.index[-1], value))
    return {"xirr": xirr(flows) * 100, "mult": value / put,
            "idle": np.mean(idle) / put * 100 if put else 0}


def main():
    syms = [str(x).strip().lower() for x in ds.FALLBACK if str(x).strip()]
    for s in syms + [ds.BENCH]:              # short copies from fetch_eod
        p = os.path.join(ds.DATA, s + ".csv")
        if os.path.exists(p) and sum(1 for _ in open(p)) < 1000:
            os.remove(p)
    P = bt.load_panels(syms, "2012-01-01")
    CL = P["Close"].ffill(limit=5)
    BM = P["BM"].ffill(limit=5)
    have = [s for s in CL.columns if CL[s].loc[:"2013-01-31"].notna().sum()
            > 200]
    print("Stocks with data from 2013: %d" % len(have))
    rows = []
    for name, a, b in PERIODS:
        base = {}
        for rule in RULES:
            n = sim(BM, rule, a, b)
            st = [sim(CL[s], rule, a, b) for s in have]
            st = [x for x in st if x]
            xs = np.array([x["xirr"] for x in st])
            if rule == "SIP monthly":
                base = {i: x for i, x in enumerate(xs)}
            beat = np.mean([x > base[i] + 0.01 for i, x in enumerate(xs)]) \
                * 100 if base else np.nan
            rows.append({"Period": name, "Rule": rule,
                         "Nifty XIRR %": round(n["xirr"], 2),
                         "Nifty idle cash %": round(n["idle"], 1),
                         "Stocks median XIRR %": round(np.median(xs), 2),
                         "Stocks worst 10% XIRR": round(np.percentile(xs, 10),
                                                        2),
                         "beats SIP monthly (stocks %)": round(beat, 0)
                         if rule != "SIP monthly" else None,
                         "Stocks idle cash %": round(np.median(
                             [x["idle"] for x in st]), 1)})
        print("done", name)
    out = pd.DataFrame(rows)
    pd.set_option("display.width", 200)
    print(out.to_string(index=False))
    out.to_csv(os.path.join(ds.DATA, "sip_backtest.csv"), index=False)


if __name__ == "__main__":
    main()
