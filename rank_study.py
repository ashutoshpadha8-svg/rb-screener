#!/usr/bin/env python3
"""
RANK STUDY  --  is the momentum rank right? Does rank 1 beat rank 20? (30 Sep 2026)
==================================================================================

RB: "agar yeh kisi stock ko rank 1 kehta hai toh short term mein kitna return
nikal sakta hai -- 15-20% chahiye. Ranking kitni sahi hai?"

Same universe as the live screener (>= Rs 10k Cr point-in-time, Rs 5 Cr
turnover). On the 1st trading day of every month 2013-01 .. 2026-09 the live
RAMOM score ranks every eligible stock on the previous close (exactly what
momentum_screener.py does). Each ranked stock is 'bought' at that day's open
and its return measured after 1, 3 and 6 months (21 / 63 / 126 sessions),
next to the equal-weight universe over the same days. No costs, no tax, no
sector cap -- this measures the RANK, not the portfolio.

Rank buckets: 1 | 2-5 | 6-10 | 11-20 | 21-40 | 41-100 | 101+ (the rest).
For each: avg / median return, % of picks >= +15% and >= +20%, % losing
more than 10%, % that beat the universe, both halves (2013-19, 2020-26).
Also the same for the RS rank (6-month return vs Nifty) the W+TT screen uses.

python3 rank_study.py            (~3 min, uses the cached price files)
"""

import warnings
warnings.filterwarnings("ignore")

import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import daily_screener as ds                                    # noqa: E402
import fusion_backtest as fb                                   # noqa: E402
import strategy_lab as sl                                      # noqa: E402

BUCKETS = [(1, 1, "1"), (2, 5, "2-5"), (6, 10, "6-10"), (11, 20, "11-20"),
           (21, 40, "21-40"), (41, 100, "41-100"), (101, 10 ** 6, "101+")]
HORIZONS = [(21, "1m"), (63, "3m"), (126, "6m")]
SPLIT = pd.Timestamp("2020-01-01")


def study(P, score, ok, name):
    O = P["Open"].values
    C = P["Close"].ffill().values
    cal = P["Close"].index
    n = len(cal)
    ew = sl.ew_index(P, ok)
    k0 = cal.searchsorted(pd.Timestamp(fb.START))
    rows = []
    for t in sorted(sl.rebal_days(cal, k0, n, "M")):
        s = score.values[t - 1]
        valid = ~np.isnan(s)
        order = np.argsort(-np.where(valid, s, -np.inf))
        ranked = [j for j in order if valid[j]]
        for r, j in enumerate(ranked, 1):
            if not O[t, j] > 0:
                continue
            row = {"t": cal[t], "rank": r}
            for h, lab in HORIZONS:
                e = t + h
                if e >= n:
                    row[lab] = np.nan
                    row[lab + " univ"] = np.nan
                    continue
                row[lab] = C[e, j] / O[t, j] - 1
                row[lab + " univ"] = ew[e] / ew[t - 1] - 1
            rows.append(row)
    d = pd.DataFrame(rows)
    out = []
    for per, m in (("2013-19", d.t < SPLIT), ("2020-26", d.t >= SPLIT),
                   ("ALL", d.t.notna())):
        for lo, hi, lab in BUCKETS:
            g = d[m & (d["rank"] >= lo) & (d["rank"] <= hi)]
            if not len(g):
                continue
            r = {"rank": name + " " + lab, "period": per,
                 "picks": len(g)}
            for _, h in HORIZONS:
                x = g[h].dropna()
                u = g[h + " univ"].reindex(x.index)
                r[h + " avg%"] = 100 * x.mean()
                r[h + " median%"] = 100 * x.median()
                r[h + " beat univ%"] = 100 * (x > u).mean()
                if h in ("3m", "6m"):
                    r[h + " >=15%"] = 100 * (x >= 0.15).mean()
                    r[h + " >=20%"] = 100 * (x >= 0.20).mean()
                    r[h + " <=-10%"] = 100 * (x <= -0.10).mean()
            out.append(r)
    return pd.DataFrame(out)


def main():
    P, uni = fb.load_pit10k()
    I = fb.indicators(P)
    elig = (uni & I["liq"]).fillna(False)
    S, ok = sl.scores(P, elig)
    res = [study(P, S["RAMOM"], ok, "MOM"),
           study(P, S["MOM6"], ok, "RS6m")]
    d = pd.concat(res, ignore_index=True)
    pd.set_option("display.width", 260)
    f = lambda x: "%.1f" % x                                   # noqa: E731
    cols1 = ["rank", "period", "picks", "1m avg%", "1m beat univ%",
             "3m avg%", "3m median%", "3m >=15%", "3m >=20%", "3m <=-10%",
             "3m beat univ%"]
    cols2 = ["rank", "period", "6m avg%", "6m median%", "6m >=15%",
             "6m >=20%", "6m <=-10%", "6m beat univ%"]
    for per in ("ALL", "2013-19", "2020-26"):
        x = d[d.period == per]
        print("\n" + "=" * 120 + "\n RANK BUCKETS -- %s (bought at the "
              "rebalance-day open, no costs)\n" % per + "=" * 120)
        print(x[cols1].to_string(index=False, float_format=f))
        print(x[cols2].to_string(index=False, float_format=f))
    d.to_csv(os.path.join(ds.DATA, "rank_study.csv"), index=False)


if __name__ == "__main__":
    main()
