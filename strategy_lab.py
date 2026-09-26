#!/usr/bin/env python3
"""
STRATEGY LAB  --  can anything beat Fusion / Weinstein+TT?
==========================================================

Same honest setup as fusion_backtest.py: >= Rs 10,000 Cr point-in-time
universe, 60-day median turnover > Rs 5 Cr, Rs 2 lakh start, real Dhan
delivery costs + 0.10% slippage per side, Indian tax (STCG 20.8%, LTCG 13%
over Rs 1.25 lakh, interest 31.2%), idle cash 6%, 2013-01 to 2026-09,
judged in 2013-19 AND 2020-26 separately (each half starts from cash).

PRE-REGISTERED STRATEGIES (fixed before looking at results, no tuning)
  Rank strategies: every month (1st trading day) rank eligible stocks on
  the previous close, hold the top N equal-weight; a holding is kept while
  its rank stays inside the top 2N (buffer, cuts turnover and tax).
    MOM12-1   12-month return skipping the last month (classic momentum)
    MOM6      6-month return (= the screener's RS)
    RAMOM     NSE Momentum-index style: average z-score of 6m and 12m
              return, each divided by 1-year volatility
    52WH      closeness to the 52-week high (George & Hwang)
    LOWVOL    lowest 1-year volatility
    RAMOM+LV  average rank of RAMOM and LOWVOL
    variants of RAMOM: top 10, quarterly rebalance, Nifty > 200DMA filter
  Mean reversion (Connors RSI-2): close > 200DMA and RSI(2) < 10 -> buy next
    open, most oversold first, 10 slots; sell when close > 5-day MA
    (next open) or after 10 sessions.
  Index timing (Nifty ETF vs liquid fund, checked monthly):
    ABSMOM  hold Nifty while its 12-month return beats 6% cash
    NIFTY200 hold Nifty while it closes above its 200-day MA

"STOCK FINDING" (separate from portfolio mechanics)
  For every pick/trade: its return minus the equal-weight return of the
  whole eligible universe over the same days. Avg excess and hit rate
  (% of picks that beat the universe) tell who finds better stocks.

RUN
  python3 ~/Desktop/RB_Screener/strategy_lab.py        (~10-15 min)
"""

import warnings
warnings.filterwarnings("ignore")

import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest as bt
import fusion_backtest as fb
from fusion_backtest import (CAPITAL, CASH_RATE, START, SPLIT, CASH_BUY,
                             CASH_SELL, CASH_SLIP, DP_CHARGE, TaxBook,
                             _fy_end, perf, nifty_curve, periods, table)


# ================================================================== scores
def zrow(x):
    return x.sub(x.mean(axis=1), axis=0).div(x.std(axis=1), axis=0)


def scores(P, elig):
    C = P["Close"].ffill(limit=5)
    r = C.pct_change().clip(-0.5, 0.5)
    vol = r.rolling(252, min_periods=200).std() * np.sqrt(252)
    m6 = C / C.shift(126) - 1
    m12 = C / C.shift(252) - 1
    ok = elig & vol.notna() & m12.notna()
    S = {}
    S["MOM12-1"] = (C.shift(21) / C.shift(252) - 1).where(ok)
    S["MOM6"] = m6.where(ok)
    S["RAMOM"] = (0.5 * zrow((m6 / vol).where(ok)) +
                  0.5 * zrow((m12 / vol).where(ok)))
    S["52WH"] = (C / C.rolling(252).max()).where(ok)
    S["LOWVOL"] = (-vol).where(ok)
    S["RAMOM+LV"] = (S["RAMOM"].rank(axis=1, pct=True) +
                     S["LOWVOL"].rank(axis=1, pct=True))
    return S, ok


# ================================================================== rank sim
def rebal_days(cal, start_k, end_k, freq="M", offset=0):
    per = cal.to_period(freq)
    days = []
    for p in pd.unique(per[start_k:end_k]):
        idx = np.flatnonzero(per == p)
        idx = idx[(idx >= start_k) & (idx < end_k)]
        if len(idx) > offset:
            days.append(int(idx[offset]))
    return set(days)


def atr_pct(P, n=14):
    """ATR(14) as % of close (Wilder)."""
    C = P["Close"].ffill(limit=5)
    H, L = P["High"], P["Low"]
    tr = np.maximum(np.maximum(H - L, (H - C.shift(1)).abs()),
                    (L - C.shift(1)).abs())
    return fb.wilder(tr, n) / C


def run_rank(P, score, N, start_k, end_k=None, freq="M", buffer=2,
             offset=0, regime=None, tax=True, capital=CAPITAL,
             cash_rate=CASH_RATE, picks=None, sector=None, sector_cap=None,
             atr=None, atr_sizing=False, trail_atr=None, breakeven=None,
             regime_blocks_buys_only=False):
    """sector: array col -> sector label; sector_cap: max holdings per sector.
    atr_sizing: slot = equal slot x (median ATR% / stock ATR%), 0.5x..2x.
    trail_atr: stop = max(entry - k*ATR, highest close - k*ATR); breakeven:
    once close >= entry*(1+breakeven) the stop is at least the entry.
    regime_blocks_buys_only: red market -> keep holdings, no new buys."""
    O = P["Open"].values
    C = P["Close"].ffill().values
    Lo = P["Low"].values
    A = atr.values if atr is not None else None
    S = score.values
    cal = P["Close"].index
    n = len(cal) if end_k is None else end_k
    reb = rebal_days(cal, start_k, n, freq, offset)
    cash, pos = capital, {}
    book = TaxBook(False)
    day_rate = (1 + cash_rate) ** (1 / 252) - 1
    eq = np.full(n, np.nan)
    trades = 0

    def sell(j, px, t):
        nonlocal cash, trades
        p = pos.pop(j)
        gross = p["sh"] * px
        fee = gross * (CASH_SELL + CASH_SLIP) + DP_CHARGE
        cash += gross - fee
        book.add(gross - fee - p["basis"], (cal[t] - cal[p["k"]]).days)
        trades += 1

    for t in range(start_k, n):
        intr = cash * day_rate if cash > 0 else 0.0
        cash += intr
        book.interest += intr
        if (trail_atr is not None or breakeven is not None) and t > start_k:
            for j in list(pos):
                p = pos[j]
                if p["k"] >= t:
                    continue
                if Lo[t, j] > 0 and Lo[t, j] <= p["stop"]:
                    px = min(O[t, j], p["stop"]) if O[t, j] > 0 else p["stop"]
                    sell(j, px, t)
                    continue
                p["hi"] = max(p["hi"], C[t, j])
                if trail_atr is not None:
                    a = A[t, j] if A[t, j] == A[t, j] else 0.0
                    p["stop"] = max(p["stop"], p["hi"] * (1 - trail_atr * a))
                if breakeven is not None and C[t, j] >= p["px"] * (1 + breakeven):
                    p["stop"] = max(p["stop"], p["px"])
        if t in reb and t > 0:
            s = S[t - 1]
            valid = ~np.isnan(s)
            order = np.argsort(-np.where(valid, s, -np.inf))
            ranked = [j for j in order if valid[j]]
            rank = {j: i for i, j in enumerate(ranked)}
            on = regime is None or bool(regime[t - 1])
            sell_all = not on and not regime_blocks_buys_only
            for j in list(pos):
                if sell_all or rank.get(j, 10 ** 9) >= buffer * N:
                    px = O[t, j] if O[t, j] > 0 else C[t - 1, j]
                    sell(j, px, t)
            if on:
                if picks is not None:
                    picks.append((t, ranked[:N]))
                mark = cash + sum(p["sh"] * C[t - 1, j] for j, p in pos.items())
                med = np.nanmedian(A[t - 1][[j for j in ranked]]) \
                    if (atr_sizing and A is not None and ranked) else None
                count = {}
                if sector is not None:
                    for j in pos:
                        count[sector[j]] = count.get(sector[j], 0) + 1
                for j in ranked:
                    if len(pos) >= N:
                        break
                    if j in pos or not O[t, j] > 0:
                        continue
                    if sector_cap is not None and sector[j] != "?" and \
                            count.get(sector[j], 0) >= sector_cap:
                        continue
                    amt = mark / N
                    if med is not None and A[t - 1, j] > 0:
                        amt *= float(np.clip(med / A[t - 1, j], 0.5, 2.0))
                    amt = min(amt, cash)
                    if amt < 1000:
                        continue
                    a = A[t - 1, j] if A is not None and A[t - 1, j] > 0 else 0.0
                    pos[j] = {"sh": amt / (O[t, j] * (1 + CASH_BUY + CASH_SLIP)),
                              "k": t, "basis": amt, "px": O[t, j],
                              "hi": O[t, j],
                              "stop": O[t, j] * (1 - (trail_atr or 0) * a)
                              if trail_atr else -1.0}
                    cash -= amt
                    if sector is not None:
                        count[sector[j]] = count.get(sector[j], 0) + 1
        if t == n - 1:
            for j in list(pos):
                sell(j, C[t, j], t)
        if tax and _fy_end(cal, t, n):
            cash -= book.settle()
        eq[t] = cash + sum(p["sh"] * C[t, j] for j, p in pos.items())
    return pd.Series(eq[start_k:n], index=cal[start_k:n]), trades


# ================================================================== index timing
def run_timing(P, on_signal, start_k, end_k=None, tax=True, capital=CAPITAL,
               cash_rate=CASH_RATE):
    """Nifty ETF when on_signal (checked on the 1st trading day of each
    month, previous close), else liquid fund. ETF cost ~0.05% + 0.05%
    slippage per side."""
    bm = P["BM"].ffill().values
    cal = P["Close"].index
    n = len(cal) if end_k is None else end_k
    reb = rebal_days(cal, start_k, n, "M", 0)
    cash, units, basis, k_in = capital, 0.0, 0.0, 0
    book = TaxBook(False)
    day_rate = (1 + cash_rate) ** (1 / 252) - 1
    eq = np.full(n, np.nan)
    switches = 0
    for t in range(start_k, n):
        intr = cash * day_rate if cash > 0 else 0.0
        cash += intr
        book.interest += intr
        if t in reb and t > 0:
            want = bool(on_signal[t - 1])
            if want and units == 0:
                units = cash * (1 - 0.001) / bm[t - 1]
                basis, k_in, cash = cash, t, 0.0
                switches += 1
            elif not want and units > 0:
                gross = units * bm[t - 1] * (1 - 0.001)
                book.add(gross - basis, (cal[t] - cal[k_in]).days)
                cash, units = cash + gross, 0.0
                switches += 1
        if t == n - 1 and units > 0:
            gross = units * bm[t] * (1 - 0.001)
            book.add(gross - basis, (cal[t] - cal[k_in]).days)
            cash, units = cash + gross, 0.0
        if tax and _fy_end(cal, t, n):
            cash -= book.settle()
        eq[t] = cash + units * bm[t]
    return pd.Series(eq[start_k:n], index=cal[start_k:n]), switches


# ================================================================== mean reversion
def mean_reversion_cands(P, elig):
    C = P["Close"].ffill(limit=5)
    d = C.diff()
    up = fb.wilder(d.clip(lower=0), 2)
    dn = fb.wilder((-d).clip(lower=0), 2)
    rsi = 100 - 100 / (1 + up / dn)
    ent = (elig & (C > C.rolling(200).mean()) & (rsi < 10)).fillna(False)
    ext = (C > C.rolling(5).mean()).fillna(False)
    O = P["Open"].values
    X = ext.values
    cal = C.index
    n = len(cal)
    first = cal.searchsorted(pd.Timestamp(START))
    rows = []
    for j in range(C.shape[1]):
        hits = np.flatnonzero(ent.values[:, j])
        for k in hits[hits >= first]:
            if k + 1 >= n or not O[k + 1, j] > 0:
                continue
            kx, px = None, None
            for t in range(k + 1, min(n, k + 11)):
                if (X[t, j] or t == k + 10) and t + 1 < n:
                    kx, px = bt._next_open(O, t + 1, j, n)
                    break
            if kx is None or px is None:
                continue
            rows.append({"col": j, "k_sig": k, "k_in": k + 1, "k_out": kx,
                         "entry": O[k + 1, j], "exit": px,
                         "rs": -float(rsi.values[k, j]), "bars": kx - k - 1,
                         "ret": px / O[k + 1, j] - 1})
    return pd.DataFrame(rows)


# ================================================================== stock finding
def ew_index(P, elig):
    C = P["Close"].ffill(limit=5)
    r = C.pct_change().clip(-0.5, 0.5).where(elig.shift(1).fillna(False))
    return (1 + r.mean(axis=1).fillna(0)).cumprod().values


def excess_trades(cand, ew, cal):
    if cand.empty:
        return pd.DataFrame()
    base = ew[cand.k_out.values] / ew[cand.k_in.values - 1] - 1
    ret = cand["exit"].values / cand["entry"].values - 1
    return pd.DataFrame({"k": cand.k_in.values, "excess": ret - base,
                         "is": cal[cand.k_in.values] < pd.Timestamp(SPLIT)})


def excess_picks(P, picks, ew, horizon=126):
    O = P["Open"].values
    C = P["Close"].ffill().values
    cal = P["Close"].index
    n = len(cal)
    rows = []
    for t, js in picks:
        e = min(t + horizon, n - 1)
        base = ew[e] / ew[t - 1] - 1
        for j in js:
            if O[t, j] > 0:
                rows.append({"k": t, "excess": C[e, j] / O[t, j] - 1 - base,
                             "is": cal[t] < pd.Timestamp(SPLIT)})
    return pd.DataFrame(rows)


def finding_row(name, ex):
    r = {"strategy": name}
    for tag, m in (("2013-19", ex["is"]), ("2020-26", ~ex["is"]),
                   ("ALL", ex["is"] | ~ex["is"])):
        x = ex.loc[m, "excess"]
        r[tag + " avg excess %"] = 100 * x.mean() if len(x) else np.nan
        r[tag + " beat univ %"] = 100 * (x > 0).mean() if len(x) else np.nan
    r["picks"] = len(ex)
    return r


# ================================================================== main
def main():
    P, uni = fb.load_pit10k()
    cal = P["Close"].index
    I = fb.indicators(P)
    elig = (uni & I["liq"]).fillna(False)
    S, ok = scores(P, elig)
    bm = P["BM"].ffill()
    regime = (bm > bm.rolling(200).mean()).values
    absmom = (bm / bm.shift(252) - 1 > CASH_RATE).values
    ew = ew_index(P, ok)

    # baselines: Fusion and W+TT (same candidate logic as fusion_backtest)
    rs = fb.rs_rank(P, uni)
    ent, ext = fb.fusion_signals(I, uni, 1)
    fus = fb.simulate_exit(P, ent, ext, rs, START, overlap=True)
    fus_c = fus[["col", "k_sig", "k_in", "k_out", "entry", "exit", "rs"]]
    sig, rsw, m150, m200 = bt.signals(P, uni)
    wtt = bt.simulate(P, sig, rsw, m150, m200, START, overlap=True)
    wtt_in = wtt[["col", "k_sig", "k_in", "k_iout", "entry", "inv_exit",
                  "rs"]].rename(columns={"k_iout": "k_out",
                                         "inv_exit": "exit"})
    mr = mean_reversion_cands(P, elig)

    rank_strats = [
        ("MOM12-1 top20 monthly", "MOM12-1", 20, "M", None),
        ("MOM6 (RS) top20 monthly", "MOM6", 20, "M", None),
        ("RAMOM top20 monthly", "RAMOM", 20, "M", None),
        ("RAMOM top10 monthly", "RAMOM", 10, "M", None),
        ("RAMOM top20 quarterly", "RAMOM", 20, "Q", None),
        ("RAMOM top20 + Nifty>200DMA", "RAMOM", 20, "M", regime),
        ("52W-high top20 monthly", "52WH", 20, "M", None),
        ("Low-vol top20 monthly", "LOWVOL", 20, "M", None),
        ("RAMOM+LowVol top20 monthly", "RAMOM+LV", 20, "M", None),
    ]
    event_strats = [("Fusion 8 slots (baseline)", fus_c, 8),
                    ("Fusion 20 slots (baseline)", fus_c, 20),
                    ("W+TT investing 20 (baseline)", wtt_in, 20),
                    ("Mean reversion RSI-2, 10 slots", mr, 10)]
    timing = [("Nifty ABSMOM (12m > cash)", absmom),
              ("Nifty > 200DMA timing", regime)]

    rows, find = [], []
    print("\nRunning %d strategies x 3 periods x pre/post tax ..."
          % (len(rank_strats) + len(event_strats) + len(timing) + 1))
    for name, key, N, freq, reg in rank_strats:
        row = {"strategy": name}
        for tag, a, b in periods(cal):
            pk = [] if tag == "FULL" else None
            pre, tr = run_rank(P, S[key], N, a, b, freq, regime=reg, tax=False,
                               picks=pk)
            post, _ = run_rank(P, S[key], N, a, b, freq, regime=reg, tax=True)
            _fill(row, tag, pre, post, tr, cal)
            if pk is not None:
                find.append(finding_row(name, excess_picks(P, pk, ew)))
        rows.append(row)
        print("  done: " + name)
    for name, c, slots in event_strats:
        row = {"strategy": name}
        for tag, a, b in periods(cal):
            pre, tr, _ = fb.run_cash(P, c, slots, a, b, tax=False)
            post, _, _ = fb.run_cash(P, c, slots, a, b, tax=True)
            _fill(row, tag, pre, post, tr, cal)
        rows.append(row)
        if "Fusion 8" not in name:
            find.append(finding_row(name, excess_trades(c, ew, cal)))
        print("  done: " + name)
    for name, sig_ in timing:
        row = {"strategy": name}
        for tag, a, b in periods(cal):
            pre, tr = run_timing(P, sig_, a, b, tax=False)
            post, _ = run_timing(P, sig_, a, b, tax=True)
            _fill(row, tag, pre, post, tr, cal)
        rows.append(row)
    row = {"strategy": "NIFTY 50 buy & hold (ETF)"}
    for tag, a, b in periods(cal):
        _fill(row, tag, nifty_curve(P, a, b, tax=False),
              nifty_curve(P, a, b, tax=True), 1, cal)
    rows.append(row)

    print("\n" + "=" * 100)
    print(" PORTFOLIOS -- Rs 2 lakh, real Dhan costs + slippage, tax, idle "
          "cash 6%  (CAGR %)")
    print("=" * 100)
    d = pd.DataFrame(rows).set_index("strategy")
    print(d.to_string(float_format=lambda x: "%.1f" % x))

    print("\n" + "=" * 100)
    print(" STOCK FINDING -- each pick/trade vs the equal-weight universe over "
          "the same days (rank picks: 6-month hold)")
    print("=" * 100)
    print(pd.DataFrame(find).set_index("strategy")
          .to_string(float_format=lambda x: "%.1f" % x))

    # robustness for the rank strategies: rebalance-day luck and N
    print("\n" + "=" * 100)
    print(" ROBUSTNESS -- FULL period post-tax CAGR: rebalance on trading day "
          "1/6/11/16 of the month, and top-N")
    print("=" * 100)
    k0 = cal.searchsorted(pd.Timestamp(START))
    rob = []
    for name, key in (("RAMOM", "RAMOM"), ("MOM12-1", "MOM12-1"),
                      ("52W-high", "52WH"), ("MOM6 (RS)", "MOM6")):
        r = {"strategy": name}
        for off in (0, 5, 10, 15):
            r["day%d" % (off + 1)] = perf(run_rank(P, S[key], 20, k0,
                                                   offset=off)[0])["CAGR%"]
        for N in (10, 15, 30):
            r["N=%d" % N] = perf(run_rank(P, S[key], N, k0)[0])["CAGR%"]
        rob.append(r)
    print(pd.DataFrame(rob).set_index("strategy")
          .to_string(float_format=lambda x: "%.1f" % x))
    print("\n%d strategies tested -> the best one is partly luck. Trust only "
          "what wins in BOTH halves and survives the robustness table."
          % len(rows))
    print("Delisted stocks are missing -> all stock strategies look a bit too "
          "good; Nifty rows are price-only (no ~1.2%/yr dividends).")


def _fill(row, tag, pre, post, trades, cal):
    pp, pt = perf(pre), perf(post)
    if tag == "FULL":
        row["FULL pre"] = pp.get("CAGR%")
        row["FULL post-tax"] = pt.get("CAGR%")
        row["maxDD"] = pp.get("maxDD%")
        yrs = (pre.index[-1] - pre.index[0]).days / 365.25
        row["trades/yr"] = trades / yrs
        row["final Rs lakh"] = pt.get("final_Rs", np.nan) / 1e5
    else:
        row[tag + " post-tax"] = pt.get("CAGR%")


if __name__ == "__main__":
    main()
