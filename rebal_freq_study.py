#!/usr/bin/env python3
"""
REBALANCE FREQUENCY STUDY (6 Oct 2026, RB: "ranking monthly rehti hai ya
daily badalti hai? daily badle to kya result?"). Pre-registered BEFORE
seeing results. The ranking is recomputed every day in live; this asks
whether ACTING on it daily / weekly beats the live monthly check.
All variants = LIVE rules: RAMOM top 20, cap mix 60/25/15 (M>L>S), sector
cap 4, keep while rank < 40, NAV/20, Rs 2 lakh, real costs + tax, cash 6%.
  MONTHLY  1st trading day of the month (live)
  WEEKLY   1st trading day of each week
  DAILY    every day: rank > 40 -> sold next open, free slots filled
Judged on BOTH halves (2013-19, 2020-26). python3 rebal_freq_study.py
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
import cap_mix_study as cm                                     # noqa: E402


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
    live = dict(cap_class=cm.cap_classes(P), cap_targets=cm.TARGETS,
                sector=sector, sector_cap=4)
    rows = []
    for name, freq in (("MONTHLY (live)", "M"), ("WEEKLY", "W"),
                       ("DAILY", "D")):
        r = {"variant": name}
        for tag, a, b in fb.periods(cal):
            pre, tr = sl.run_rank(P, S["RAMOM"], 20, a, b, freq, tax=False,
                                  **live)
            post, _ = sl.run_rank(P, S["RAMOM"], 20, a, b, freq, tax=True,
                                  **live)
            sl._fill(r, tag, pre, post, tr, cal)
            if tag == "FULL":
                r["worst yr %"] = (post.resample("YE").last().pct_change()
                                   .min() * 100)
        rows.append(r)
        print("  done %s" % name, flush=True)
    pd.set_option("display.width", 250)
    print("\n" + pd.DataFrame(rows).set_index("variant").to_string(
        float_format=lambda x: "%.1f" % x))


if __name__ == "__main__":
    main()
