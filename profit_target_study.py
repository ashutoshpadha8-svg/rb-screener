#!/usr/bin/env python3
"""
PROFIT TARGET STUDY (6 Oct 2026, RB: "mujhe sirf momentum capture karna hai,
max 25-30%"). Pre-registered BEFORE seeing results:

  C = LIVE momentum: RAMOM top 20, sector cap 4, cap mix 60/25/15 (M>L>S),
      keep while rank < 40, monthly, NAV/20, Rs 2 lakh, real costs + tax,
      idle cash 6%.
  A = C + sell at +25% (day's high touches entry x 1.25 -> sold at that
      price, or the open if it gaps above = resting limit/GTT sell).
  B = C + sell at +30%, same way.
  In A/B the freed cash waits for the next monthly rebalance and buys the
  top 20 then (the same stock may be bought again if it is still ranked).
Judged on BOTH halves (2013-19, 2020-26), post-tax.
python3 profit_target_study.py
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
    live = {"cap_class": cls, "cap_targets": cm.TARGETS}
    rows = []
    for name, tgt in (("C live (rank > 40 exit)", None),
                      ("A + sell at +25%", 0.25),
                      ("B + sell at +30%", 0.30)):
        r = {"variant": name}
        for tag, a, b in fb.periods(cal):
            st = {}
            pre, tr = sl.run_rank(P, S["RAMOM"], 20, a, b, "M", tax=False,
                                  sector=sector, sector_cap=4, target=tgt,
                                  stats=st, **live)
            post, _ = sl.run_rank(P, S["RAMOM"], 20, a, b, "M", tax=True,
                                  sector=sector, sector_cap=4, target=tgt,
                                  **live)
            sl._fill(r, tag, pre, post, tr, cal)
            if tag == "FULL":
                yrs = (pre.index[-1] - pre.index[0]).days / 365.25
                r["target sells/yr"] = st.get("target_exits", 0) / yrs
                r["2L -> Rs lakh (post)"] = post.iloc[-1] / 1e5
        rows.append(r)
        print("  done %s" % name, flush=True)
    pd.set_option("display.width", 220)
    print("\n" + pd.DataFrame(rows).set_index("variant").to_string(
        float_format=lambda x: "%.1f" % x))


if __name__ == "__main__":
    main()
