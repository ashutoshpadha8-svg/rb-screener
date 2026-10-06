#!/usr/bin/env python3
"""
TOP-10 STUDY (6 Oct 2026, RB: "weekly top 10 ka bhi test karo").
Pre-registered BEFORE seeing results. Live rules otherwise: RAMOM rank,
sector cap 4, NAV/N, Rs 2 lakh, real costs + tax, cash 6%. Cap mix for 10
slots = 6 MID / 3 LARGE / 1 SMALL (60/25/15 rounded), leftovers M > L > S.
  M10   monthly, 10 slots, sell when rank > 20 (2 x N, same rule as top 20)
  W10a  weekly,  10 slots, sell when rank > 20
  W10b  weekly,  10 slots, sell when rank > 40 (live's buffer level)
Reference: live monthly top 20 (rebal_freq_study / profit_target_study).
Judged on BOTH halves (2013-19, 2020-26). python3 top10_study.py
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

TARGETS10 = {"M": 6, "L": 3, "S": 1}


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
    base = dict(cap_class=cm.cap_classes(P), sector=sector, sector_cap=4)
    rows = []
    for name, N, freq, kw in (
            ("M20 live monthly top20, rank>40", 20, "M",
             dict(cap_targets=cm.TARGETS, buffer=2)),
            ("M10 monthly top10, rank>20", 10, "M",
             dict(cap_targets=TARGETS10, buffer=2)),
            ("W10a weekly top10, rank>20", 10, "W",
             dict(cap_targets=TARGETS10, buffer=2)),
            ("W10b weekly top10, rank>40", 10, "W",
             dict(cap_targets=TARGETS10, buffer=4))):
        r = {"variant": name}
        for tag, a, b in fb.periods(cal):
            pre, tr = sl.run_rank(P, S["RAMOM"], N, a, b, freq, tax=False,
                                  **base, **kw)
            post, _ = sl.run_rank(P, S["RAMOM"], N, a, b, freq, tax=True,
                                  **base, **kw)
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
