#!/usr/bin/env python3
"""
MOMENTUM LAB  --  can the live momentum strategy be made better? (29 Sep 2026)
=============================================================================

BASE = what runs live (momentum_screener.py): RAMOM score (0.5 z(6m ret/vol) +
0.5 z(12m ret/vol)), top 20, max 4 per NSE industry, monthly on the 1st
trading day, keep while rank < 40. Same honest setup as strategy_lab.py
(>= Rs 10k Cr point-in-time, Rs 5 Cr turnover, Rs 2 lakh, Dhan costs +
0.10% slippage, tax, idle cash 6%, 2013-19 AND 2020-26 judged separately).

PRE-REGISTERED IDEAS (from published research, fixed before running)
  1 BLEND     50% BASE + 50% low-volatility top 20 (two sleeves, Rs 1 lakh
              each, never re-balanced between them). Low-vol led 2013-19
              when momentum lagged.
  2 SMOOTH    "frog in the pan" (Da, Gurun, Warachka 2014): score =
              0.5 z(RAMOM) + 0.5 z(-ID), ID = sign(12m ret) x (% down days -
              % up days) over 252 days -> steady risers rank higher.
  3 RESIDUAL  residual momentum (Blitz, Huij, Martens): daily return minus
              beta x Nifty (252-day beta); score = sum of residuals months
              t-12..t-1 / their std. Less crash-prone in the literature.
  4 VOLMGD    volatility-managed (Barroso & Santa-Clara 2015): each month
              invest w = min(1, 18% / realised 126-day vol of the BASE
              portfolio), rest in cash at 6%; 0.3% cost on the change in w.
              (Applied to the BASE post-tax curve -> approximation.)
  Ideas 2-3 keep top 20 + sector cap 4 + monthly + rank < 40 like BASE.
  A winner must beat BASE in BOTH halves (and not by a hair).

python3 momentum_lab.py      (~10 min, uses the price files backtest.py keeps)
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
from fusion_backtest import CAPITAL, CASH_RATE, perf           # noqa: E402

N, CAP = 20, 4
VOL_TARGET, VOL_WIN, VOL_COST = 0.18, 126, 0.003


def extra_scores(P, ok, S):
    C = P["Close"].ffill(limit=5)
    r = C.pct_change().clip(-0.5, 0.5)
    m12 = C / C.shift(252) - 1
    up = (r > 0).astype(float).rolling(252, min_periods=200).mean()
    dn = (r < 0).astype(float).rolling(252, min_periods=200).mean()
    ID = np.sign(m12) * (dn - up)
    smooth = (0.5 * sl.zrow(S["RAMOM"].where(ok)) +
              0.5 * sl.zrow((-ID).where(ok)))
    rm = P["BM"].ffill(limit=5).pct_change()
    var = rm.rolling(252, min_periods=200).var()
    beta = r.rolling(252, min_periods=200).cov(rm).div(var, axis=0)
    e = r - beta.shift(1).mul(rm, axis=0)
    e = e.shift(21)
    resid = (e.rolling(231, min_periods=180).sum() /
             e.rolling(231, min_periods=180).std()).where(ok)
    return smooth, resid


def vol_managed(eq, cal, a):
    """Scale the BASE curve monthly by target / trailing realised vol."""
    r = eq.pct_change().fillna(0.0).values
    idx = eq.index
    reb = set(sl.rebal_days(cal, a, a + len(eq), "M"))
    day_rate = (1 + CASH_RATE) ** (1 / 252) - 1
    w, v, out = 1.0, CAPITAL, []
    for i in range(len(r)):
        k = a + i
        if k in reb and i > VOL_WIN:
            vol = np.std(r[i - VOL_WIN:i]) * np.sqrt(252)
            nw = min(1.0, VOL_TARGET / vol) if vol > 0 else 1.0
            v *= 1 - VOL_COST * abs(nw - w)
            w = nw
        v *= 1 + w * r[i] + (1 - w) * day_rate
        out.append(v)
    return pd.Series(out, index=idx)


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
    smooth, resid = extra_scores(P, ok, S)
    kw = dict(sector=sector, sector_cap=CAP)

    def rank_run(score, a, b, tax, cap=CAPITAL, use_cap=True):
        return sl.run_rank(P, score, N, a, b, "M", tax=tax, capital=cap,
                           **(kw if use_cap else {}))

    variants = {
        "BASE RAMOM top20 + sector cap (live)":
            lambda a, b, t: rank_run(S["RAMOM"], a, b, t),
        "1 BLEND 50% BASE + 50% low-vol":
            lambda a, b, t: _blend(rank_run(S["RAMOM"], a, b, t, CAPITAL / 2),
                                   rank_run(S["LOWVOL"], a, b, t, CAPITAL / 2,
                                            use_cap=False)),
        "2 SMOOTH (frog in the pan)":
            lambda a, b, t: rank_run(smooth, a, b, t),
        "3 RESIDUAL momentum":
            lambda a, b, t: rank_run(resid, a, b, t),
        "4 VOLMGD (vol target 18%)":
            lambda a, b, t: _vm(rank_run(S["RAMOM"], a, b, t), cal, a),
        "ref: low-vol top20 alone":
            lambda a, b, t: rank_run(S["LOWVOL"], a, b, t, use_cap=False),
    }
    rows = []
    for name, fn in variants.items():
        row = {"strategy": name}
        for tag, a, b in fb.periods(cal):
            pre, tr = fn(a, b, False)
            post, _ = fn(a, b, True)
            sl._fill(row, tag, pre, post, tr, cal)
            if tag == "FULL":
                row["worst 12m %"] = _worst12(post)
        rows.append(row)
        print("  done: " + name, flush=True)
    row = {"strategy": "NIFTY 50 buy & hold"}
    for tag, a, b in fb.periods(cal):
        n = fb.nifty_curve(P, a, b, tax=True)
        sl._fill(row, tag, fb.nifty_curve(P, a, b, tax=False), n, 1, cal)
        if tag == "FULL":
            row["worst 12m %"] = _worst12(n)
    rows.append(row)

    pd.set_option("display.width", 250)
    d = pd.DataFrame(rows).set_index("strategy")
    print("\n" + "=" * 110)
    print(" MOMENTUM LAB -- Rs 2 lakh, Dhan costs + slippage, tax, idle cash "
          "6% (CAGR %, post-tax unless 'pre')")
    print("=" * 110)
    print(d.to_string(float_format=lambda x: "%.1f" % x))
    d.to_csv(os.path.join(ds.DATA, "momentum_lab.csv"))
    print("\n4 ideas tested -> keep one only if it beats BASE in BOTH halves.")


def _blend(x, y):
    (e1, t1), (e2, t2) = x, y
    return e1.add(e2, fill_value=0), t1 + t2


def _vm(x, cal, a):
    e, t = x
    return vol_managed(e, cal, a), t


def _worst12(e):
    e = e.dropna()
    r = e / e.shift(252) - 1
    return 100 * r.min() if len(r.dropna()) else np.nan


if __name__ == "__main__":
    main()
