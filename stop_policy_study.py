#!/usr/bin/env python3
"""
STOP POLICY STUDY (30 Sep 2026, Codex review): the swing backtest fills the
20% stop INTRADAY at the stop price (or the open on a gap). Live code has no
resting stop: it sees the day's low under the stop after the close and sends
a next-open AMO. Does that change the numbers? Same W+TT signals (pit10k),
one trade per stock, 0.25%/side.

  A  backtest   : low <= stop -> exit same day at min(open, stop)
  B  live today : low <= stop -> exit NEXT open
  C  close stop : CLOSE <= stop -> exit next open (no intraday wick exits)
40w-MA exit identical in all three. python3 stop_policy_study.py
"""
import warnings
warnings.filterwarnings("ignore")
import os, sys
import numpy as np
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest as bt                                          # noqa: E402
import fusion_backtest as fb                                   # noqa: E402
from fusion_backtest import START, SPLIT                       # noqa: E402


def run(P, sig, m200, policy):
    O, L, C = (P[k].values for k in ("Open", "Low", "Close"))
    M = m200.values
    cal = P["Close"].index
    n, first = len(cal), cal.searchsorted(pd.Timestamp(START))
    out = []
    for j in range(P["Close"].shape[1]):
        busy = -1
        for k in np.flatnonzero(sig.values[:, j]):
            if k < first or k <= busy or k + 1 >= n or not O[k + 1, j] > 0:
                continue
            e = O[k + 1, j]
            stop = e * (1 - bt.STOP)
            sx, sp, why = n - 1, C[n - 1, j], "open"
            for t in range(k + 1, n):
                hit = (C[t, j] <= stop) if policy == "C" else (L[t, j] <= stop)
                if hit:
                    if policy == "A":
                        sx, sp = t, (min(O[t, j], stop) if O[t, j] > 0
                                     else stop)
                    else:
                        sx, sp = bt._next_open(O, t + 1, j, n) \
                            if t + 1 < n else (n - 1, C[n - 1, j])
                    why = "stop"
                    break
                if C[t, j] < M[t, j] and t + 1 < n:
                    sx, sp = bt._next_open(O, t + 1, j, n)
                    why = "40w MA"
                    break
            if not sp > 0:
                sx, sp = n - 1, C[n - 1, j]
            busy = sx
            out.append({"k_in": k + 1, "why": why,
                        "ret": sp * (1 - bt.COST) / (e * (1 + bt.COST)) - 1})
    return pd.DataFrame(out)


def main():
    P, uni = fb.load_pit10k()
    cal = P["Close"].index
    sig, rsw, m150, m200 = bt.signals(P, uni)
    rows = []
    for pol, name in (("A", "A backtest (intraday stop)"),
                      ("B", "B live now (low hit -> next open)"),
                      ("C", "C close below stop -> next open")):
        t = run(P, sig, m200, pol)
        is_ = cal[t.k_in.values] < pd.Timestamp(SPLIT)
        st = t[t.why == "stop"].ret
        r = {"policy": name, "trades": len(t),
             "avg% 13-19": 100 * t[is_].ret.mean(),
             "avg% 20-26": 100 * t[~is_].ret.mean(),
             "avg% ALL": 100 * t.ret.mean(), "win%": 100 * (t.ret > 0).mean(),
             "stop exits": len(st), "avg stop loss%": 100 * st.mean(),
             "worst stop%": 100 * st.min(),
             "stops worse than -25%": int((st < -0.25).sum())}
        rows.append(r)
        print("  done " + name, flush=True)
    pd.set_option("display.width", 220)
    print(pd.DataFrame(rows).set_index("policy").to_string(
        float_format=lambda x: "%.1f" % x))


if __name__ == "__main__":
    main()
