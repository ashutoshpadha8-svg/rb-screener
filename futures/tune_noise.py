"""
Tune NOISE (intraday momentum) for Topstep Combine pass rate.
Tuning uses ONLY 2016-2021. The chosen config is then checked on 2022-2026 (never used for choosing).

Run:
  python3 tune_noise.py data/usatechidxusd-m1-bid-2016-01-01-2026-09-26.csv MNQ

Variants tested:
  freq       - decision every 15 or 30 minutes (paper: 30)
  hard_stop  - exit intrabar when price crosses the trailing band/VWAP stop, instead of waiting for next check
  max_trades - max entries per day (1, 2, unlimited)
  budget     - $ per one average daily range (vol-targeted sizing, paper-style). NQ range ~200 pts = $400/micro
"""
import itertools
import sys

import numpy as np
import pandas as pd

import backtest as bt

MAX_DAYS = 60   # give up after ~3 months of subscription fees; counted as NOT passed


def strat_noise2(days, freq=30, hard_stop=False, max_trades=99, lookback=14):
    out = []
    moves, ranges = [], []
    for day in days:
        o = day["o"][0]
        if len(moves) >= lookback and not np.isnan(day["prev_close"]):
            sigma = np.mean(moves[-lookback:], axis=0)
            avg_range = np.mean(ranges[-lookback:])
            ub = max(o, day["prev_close"]) * (1 + sigma)
            lb = min(o, day["prev_close"]) * (1 - sigma)
            vw = bt.vwap_proxy(day)
            pos, entry, i_in, stop, n_tr = 0, 0.0, 0, 0.0, 0
            i = 30
            last_check = 30
            while i < 390:
                if i == last_check:
                    c = day["c"][i - 1]
                    if pos == 1:
                        stop = max(stop, ub[i - 1], vw[i - 1])
                        if c < stop:
                            out.append(bt.trade(day["date"], 1, entry, c, avg_range, bt.mae(day, 1, entry, i_in, i - 1)))
                            pos = 0
                    elif pos == -1:
                        stop = min(stop, lb[i - 1], vw[i - 1])
                        if c > stop:
                            out.append(bt.trade(day["date"], -1, entry, c, avg_range, bt.mae(day, -1, entry, i_in, i - 1)))
                            pos = 0
                    if pos == 0 and n_tr < max_trades and i < 385:
                        if c > ub[i - 1]:
                            pos, entry, i_in, stop, n_tr = 1, c, i, max(ub[i - 1], vw[i - 1]), n_tr + 1
                        elif c < lb[i - 1]:
                            pos, entry, i_in, stop, n_tr = -1, c, i, min(lb[i - 1], vw[i - 1]), n_tr + 1
                    last_check += freq
                # intrabar stop check (after the decision made on the previous bar's close)
                if hard_stop and pos != 0 and i >= i_in:
                    if (pos == 1 and day["l"][i] <= stop) or (pos == -1 and day["h"][i] >= stop):
                        fill = min(stop, day["o"][i]) if pos == 1 else max(stop, day["o"][i])  # gap through stop
                        out.append(bt.trade(day["date"], pos, entry, fill, avg_range,
                                            bt.mae(day, pos, entry, i_in, i)))
                        pos = 0
                i += 1
            if pos != 0:
                out.append(bt.trade(day["date"], pos, entry, day["c"][-1], avg_range, bt.mae(day, pos, entry, i_in, 389)))
        moves.append(np.abs(day["c"] / o - 1))
        ranges.append(day["h"].max() - day["l"].min())
    return out


def evaluate(raw, budget, pv, tick, dates_is, dates_oos):
    bt.RISK_PER_TRADE = budget
    t = bt.to_dollars(raw, pv, tick)
    res = {}
    for label, part, dates in (("IS", t[t["date"] <= bt.IS_END], dates_is),
                               ("OOS", t[t["date"] > bt.IS_END], dates_oos)):
        s = bt.stats(part, "pnl1")
        c = bt.combine_sim(part, dates, MAX_DAYS)
        z = part.copy()
        z["pnl"] = z["pnl"] - z["pnl"].mean()
        c0 = bt.combine_sim(z, dates, MAX_DAYS)
        res[label] = {"pass%": c["pass%"], "base%": c0["pass%"], "days": c["med_days_to_pass"],
                      "PF": s["PF"], "sharpe": s["sharpe"], "micros": part["n"].mean()}
    return res


def main():
    path, sym = sys.argv[1], sys.argv[2]
    pv, tick = bt.SPECS[sym]
    days = bt.day_table(bt.load(path))
    dates = [d["date"] for d in days]
    d_is = [d for d in dates if d <= pd.Timestamp(bt.IS_END)]
    d_oos = [d for d in dates if d > pd.Timestamp(bt.IS_END)]
    rows = []
    for freq, hs, mt in itertools.product([15, 30], [False, True], [1, 2, 99]):
        raw = strat_noise2(days, freq, hs, mt)
        for budget in [400, 800, 1200, 1600, 2400]:
            r = evaluate(raw, budget, pv, tick, d_is, d_oos)
            rows.append({"freq": freq, "hard_stop": hs, "max_tr": mt, "budget": budget,
                         "micros": round(r["IS"]["micros"], 1),
                         "IS_pass%": round(r["IS"]["pass%"], 1), "IS_base%": round(r["IS"]["base%"], 1),
                         "IS_PF": round(r["IS"]["PF"], 2), "IS_days": r["IS"]["days"],
                         "OOS_pass%": round(r["OOS"]["pass%"], 1), "OOS_base%": round(r["OOS"]["base%"], 1),
                         "OOS_PF": round(r["OOS"]["PF"], 2), "OOS_days": r["OOS"]["days"]})
    out = pd.DataFrame(rows).sort_values("IS_pass%", ascending=False)
    pd.set_option("display.width", 220)
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
