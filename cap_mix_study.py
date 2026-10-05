#!/usr/bin/env python3
"""
CAP MIX STUDY (5 Oct 2026, RB: "maximum midcap, phir largecap, last smallcap
= 60/25/15; agar 6 midcap nahi milte to next preference"). Pre-registered
BEFORE seeing results:

  BASE  = LIVE momentum: RAMOM top 20, sector cap 4, keep while rank < 40,
          monthly, NAV/20, Rs 2 lakh, real costs + tax, idle cash 6%.
  MIX   = same, but new buys fill 12 MID + 5 LARGE + 3 SMALL slots (60/25/15)
          in rank order; slots a class cannot fill go to MID first, then
          LARGE, then SMALL. Holdings are kept by the same rank-40 rule.

Cap class like AMFI, point in time: rank by estimated market cap among all
loaded NSE stocks that day: 1-100 LARGE, 101-250 MID, 251+ SMALL (all inside
the >= Rs 10,000 Cr universe). Estimated cap = today's cap x price ratio
(survivor universe; ~2.5% median error vs real NSE files 2024-26).
Judged on BOTH halves (2013-19, 2020-26). python3 cap_mix_study.py
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

TARGETS = {"M": 12, "L": 5, "S": 3}
LARGE, MID = 100, 250


def cap_classes(P):
    m, asof, src = ds.fetch_mcap()
    mc = m.set_index(m.symbol.str.lower())["mcap_cr"]
    C = P["Close"].ffill(limit=5)
    est = C * (mc.reindex(C.columns) / C.ffill().iloc[-1])
    rk = est.rank(axis=1, ascending=False, method="first")
    cls = np.where(rk <= LARGE, "L", np.where(rk <= MID, "M", "S"))
    return np.where(est.isna().values, "?", cls)


def main():
    P, uni = fb.load_pit10k()
    cal = P["Close"].index
    I = fb.indicators(P)
    elig = (uni & I["liq"]).fillna(False)
    S, ok = sl.scores(P, elig)
    ind = pd.read_csv(os.path.join(ds.DATA, "_nse_industry.csv"))
    m = dict(zip(ind.Symbol.astype(str).str.lower(), ind.Industry))
    sector = np.array([m.get(c, "?") for c in P["Close"].columns],
                      dtype=object)
    cls = cap_classes(P)
    rows, mixes = [], {}
    for name, kw in (("BASE live (rank only)", {}),
                     ("MIX 60/25/15 mid>large>small",
                      {"cap_class": cls, "cap_targets": TARGETS})):
        r = {"variant": name}
        for tag, a, b in fb.periods(cal):
            pk = [] if tag == "FULL" else None
            pre, tr = sl.run_rank(P, S["RAMOM"], 20, a, b, "M", tax=False,
                                  sector=sector, sector_cap=4, **kw)
            post, _ = sl.run_rank(P, S["RAMOM"], 20, a, b, "M", tax=True,
                                  sector=sector, sector_cap=4, picks=pk, **kw)
            sl._fill(r, tag, pre, post, tr, cal)
        rows.append(r)
        print("  done %s" % name, flush=True)
    # what the plain rank list looks like by class (top 20 at each rebalance)
    comp = []
    for t in sorted(sl.rebal_days(cal, 252, len(cal))):
        s = S["RAMOM"].values[t - 1]
        valid = ~np.isnan(s)
        top = [j for j in np.argsort(-np.where(valid, s, -np.inf))
               if valid[j]][:20]
        c = pd.Series(cls[t - 1][top]).value_counts()
        comp.append({"date": cal[t], **{k: int(c.get(k, 0))
                                        for k in ("L", "M", "S")}})
    comp = pd.DataFrame(comp)
    pd.set_option("display.width", 220)
    print("\n" + pd.DataFrame(rows).set_index("variant").to_string(
        float_format=lambda x: "%.1f" % x))
    print("\nRAMOM raw top 20 by cap class (avg per rebalance):")
    for lab, g in (("2013-19", comp[comp.date.dt.year <= 2019]),
                   ("2020-26", comp[comp.date.dt.year >= 2020])):
        print("  %s  LARGE %.1f  MID %.1f  SMALL %.1f   (months with < 12 "
              "MID: %d of %d)" % (lab, g.L.mean(), g.M.mean(), g.S.mean(),
                                  int((g.M < 12).sum()), len(g)))


if __name__ == "__main__":
    main()
