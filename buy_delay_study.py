#!/usr/bin/env python3
"""
BUY DELAY STUDY (30 Sep 2026, Codex recheck): live rbtrack now sends the
momentum rebalance BUYs only after the SELLs are confirmed = one session
later than the backtest (sells and buys at the same open). Does that cost
return? LIVE setup: RAMOM top 20, sector cap 4, keep rank <= 40, monthly,
Rs 2 lakh, Dhan costs + slippage, tax, idle cash 6%. Cash from the sells
waits (earning 6%) until the buy day.

  delay 0 = backtest as before      delay 1 = live now      delay 2 = check
python3 buy_delay_study.py
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
    rows = []
    for d in (0, 1, 2):
        r = {"buy delay (sessions)": d}
        for tag, a, b in fb.periods(cal):
            pre, tr = sl.run_rank(P, S["RAMOM"], 20, a, b, "M", tax=False,
                                  sector=sector, sector_cap=4, buy_delay=d)
            post, _ = sl.run_rank(P, S["RAMOM"], 20, a, b, "M", tax=True,
                                  sector=sector, sector_cap=4, buy_delay=d)
            sl._fill(r, tag, pre, post, tr, cal)
        rows.append(r)
        print("  done delay %d" % d, flush=True)
    pd.set_option("display.width", 220)
    print(pd.DataFrame(rows).set_index("buy delay (sessions)").to_string(
        float_format=lambda x: "%.1f" % x))


if __name__ == "__main__":
    main()
