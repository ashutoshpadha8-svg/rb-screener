#!/usr/bin/env python3
"""
DAILY TOP-5 STUDY (6 Oct 2026, RB: "ranking har scan mein badle, har baar
rank 1-5 wale khareedo, SL 10% lagao, dobara signal mile to lo, maximum
target ka wait karo"). Pre-registered BEFORE seeing results.
Common: RAMOM rank, >= Rs 10k Cr pit universe + liquidity, Rs 2 lakh, NAV/N
whole shares, real Dhan costs + 0.1% slippage, tax, idle cash 6%, sector
cap 4, 2013-01..2026-09, judged on BOTH halves.

  C   LIVE: monthly top 20, cap mix 60/25/15, keep while rank < 40
  M5  monthly, 5 slots, buy only rank 1-5, keep while rank < 40, no SL
  D1  RB: DAILY ranking, 5 slots, buy only rank 1-5 (next open), fixed SL
      10% below entry, also sell when rank > 40, re-buy if back in top 5
  D2  DAILY, 5 slots, rank 1-5, TRAILING 10% SL (from the highest close),
      no rank exit (= "maximum target ka wait")
  D3  DAILY, 5 slots, rank 1-5, NO SL, sell when rank > 40 (what the SL adds)
python3 daily_top5_study.py
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
    cls = cm.cap_classes(P)
    V = [("C  live monthly top20 + cap mix", 20, "M",
          dict(cap_class=cls, cap_targets=cm.TARGETS)),
         ("M5 monthly top5, no SL", 5, "M", dict(buffer=8, buy_within=5)),
         ("D1 daily top5, SL 10% + rank>40", 5, "D",
          dict(buffer=8, buy_within=5, stop_pct=0.10)),
         ("D2 daily top5, trailing SL 10%", 5, "D",
          dict(buffer=10 ** 6, buy_within=5, trail_pct=0.10)),
         ("D3 daily top5, no SL, rank>40", 5, "D",
          dict(buffer=8, buy_within=5))]
    rows = []
    for name, N, freq, kw in V:
        r = {"variant": name}
        for tag, a, b in fb.periods(cal):
            st = {}
            pre, tr = sl.run_rank(P, S["RAMOM"], N, a, b, freq, tax=False,
                                  sector=sector, sector_cap=4, stats=st, **kw)
            post, _ = sl.run_rank(P, S["RAMOM"], N, a, b, freq, tax=True,
                                  sector=sector, sector_cap=4, **kw)
            sl._fill(r, tag, pre, post, tr, cal)
            if tag == "FULL":
                yrs = (pre.index[-1] - pre.index[0]).days / 365.25
                r["SL sells/yr"] = st.get("stop_exits", 0) / yrs
                r["worst yr %"] = (post.resample("YE").last().pct_change()
                                   .min() * 100)
        rows.append(r)
        print("  done %s" % name, flush=True)
    pd.set_option("display.width", 250)
    print("\n" + pd.DataFrame(rows).set_index("variant").to_string(
        float_format=lambda x: "%.1f" % x))


if __name__ == "__main__":
    main()
