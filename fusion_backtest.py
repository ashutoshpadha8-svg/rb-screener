#!/usr/bin/env python3
"""
FUSION STRATEGY BACKTEST  --  cash market AND stock futures (F&O)
=================================================================

FUSION RULES (from the earlier chat, unchanged)
  Long entry  : EMA20 > EMA50, MACD(12,26,9) line > signal AND > 0,
                MFI(14) > 60, ADX(14) > 20, close >= upper Bollinger(20,2)
                -> buy next open
  Long exit   : EMA20 < EMA50 on a close -> sell next open. No stop.
  Short (F&O only, mirror image): EMA20 < EMA50, MACD < signal AND < 0,
                MFI < 40, ADX > 20, close <= lower Bollinger -> short next
                open; cover when EMA20 > EMA50.
  Same liquidity floor as the screener: 60-day median turnover > Rs 5 Cr.
  Indicators on adjusted spot prices (eod2_data).

WHAT IS COMPARED (all on the same data, same engine)
  Fusion | Weinstein+TT swing exit | Weinstein+TT investing exit |
  Fusion+W+TT pooled | Nifty 50
  Universe: >= Rs 10,000 Cr point-in-time (backtest.py pit10k) for cash;
  stocks that had futures THAT DAY (NSE F&O bhavcopy) for F&O.
  In-sample 2013-2019 and out-of-sample 2020-2026, each from cash.

REAL COSTS (Dhan pricing page, 26 Sep 2026; NSE exchange charges)
  Cash delivery : brokerage 0, STT 0.1% buy+sell, exchange 0.00307%,
                  SEBI 0.0001%, GST 18% on (exchange+SEBI), stamp 0.015% buy,
                  DP Rs 12.50 + GST per sell, slippage 0.10% per side.
  Stock futures : brokerage Rs 20 + GST per order, STT 0.025% sell,
                  exchange 0.00173%, SEBI 0.0001%, stamp 0.002% buy,
                  slippage 0.03% per side; a roll = close + open (2 orders).
  Futures P&L uses the ACTUAL contract prices (carry/basis included), near
  month, rolled 3 sessions before expiry. Collateral earns 6%/yr.

TAX (today's rules applied to all years, so strategies compare fairly)
  Cash  : STCG 20% (+4% cess), LTCG 12.5% (+cess) above Rs 1.25 lakh/FY,
          Indian set-off rules, losses carried forward.
  F&O   : business income at 30% slab (+cess = 31.2%), losses carried fwd.
  Interest on idle cash: 31.2%. Tax is paid at each 31 March.
  Everything is sold on the last day and taxed, benchmark included.

KNOWN LIMITS
  * Stocks delisted before today are missing (eod2 has only live symbols)
    -> results a bit too good. Renamed F&O symbols are lost.
  * Fractional shares / lots in the portfolio maths; the separate "Rs 2
    lakh" table shows what real lot sizes allow.
  * Nifty benchmark = price index; dividends (~1.2%/yr) not included.

RUN
  python3 fno_data.py              # once, downloads F&O history
  python3 fusion_backtest.py       # everything (10-20 min)
  python3 fusion_backtest.py --cash-only
"""

import warnings
warnings.filterwarnings("ignore")

import os
import sys
import datetime as dt

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import daily_screener as ds
import backtest as bt

CAPITAL = 200000.0
CASH_RATE = 0.06
START = "2013-01-01"
SPLIT = "2020-01-01"

# ---------------------------------------------------------------- costs
EXCH_EQ, EXCH_FUT, SEBI, GST = 0.0000307, 0.0000173, 0.000001, 0.18
CASH_BUY = 0.001 + 0.00015 + (EXCH_EQ + SEBI) * (1 + GST)
CASH_SELL = 0.001 + (EXCH_EQ + SEBI) * (1 + GST)
CASH_SLIP = 0.001
DP_CHARGE = 12.5 * (1 + GST)
FUT_BROK = 20 * (1 + GST)
FUT_BUY = 0.00002 + (EXCH_FUT + SEBI) * (1 + GST)
FUT_SELL = 0.00025 + (EXCH_FUT + SEBI) * (1 + GST)
FUT_SLIP = 0.0003
ROLL_DAYS = 3
MARGIN = 0.25            # SPAN + exposure, typical for stock futures

# ---------------------------------------------------------------- tax
CESS = 1.04
STCG, LTCG, LTCG_FREE = 0.20 * CESS, 0.125 * CESS, 125000.0
SLAB = 0.30 * CESS


# ================================================================== indicators
def ema(x, n):
    return x.ewm(span=n, adjust=False, min_periods=n).mean()


def wilder(x, n):
    return x.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def indicators(P):
    C = P["Close"].ffill(limit=5)
    H, L, V = P["High"], P["Low"], P["Volume"]
    I = {"C": C}
    I["e20"], I["e50"] = ema(C, 20), ema(C, 50)
    macd = ema(C, 12) - ema(C, 26)
    I["macd"], I["sig"] = macd, ema(macd, 9)
    tp = (H + L + C) / 3
    mf = tp * V
    up = mf.where(tp > tp.shift(1), 0.0)
    dn = mf.where(tp < tp.shift(1), 0.0)
    ratio = up.rolling(14).sum() / dn.rolling(14).sum()
    I["mfi"] = 100 - 100 / (1 + ratio)
    pdm = H.diff()
    ndm = -L.diff()
    pdm = pdm.where((pdm > ndm) & (pdm > 0), 0.0)
    ndm = ndm.where((ndm > pdm) & (ndm > 0), 0.0)
    tr = np.maximum(np.maximum(H - L, (H - C.shift(1)).abs()),
                    (L - C.shift(1)).abs())
    atr = wilder(tr, 14)
    pdi = 100 * wilder(pdm, 14) / atr
    ndi = 100 * wilder(ndm, 14) / atr
    dx = 100 * (pdi - ndi).abs() / (pdi + ndi)
    I["adx"] = wilder(dx, 14)
    mid = C.rolling(20).mean()
    sd = C.rolling(20).std(ddof=0)
    I["bbu"], I["bbl"] = mid + 2 * sd, mid - 2 * sd
    I["liq"] = (C * V).rolling(60).median() > 5e7
    return I


def fusion_signals(I, universe, side=1):
    if side > 0:
        ent = ((I["e20"] > I["e50"]) & (I["macd"] > I["sig"]) &
               (I["macd"] > 0) & (I["mfi"] > 60) & (I["adx"] > 20) &
               (I["C"] >= I["bbu"]))
        ext = I["e20"] < I["e50"]
    else:
        ent = ((I["e20"] < I["e50"]) & (I["macd"] < I["sig"]) &
               (I["macd"] < 0) & (I["mfi"] < 40) & (I["adx"] > 20) &
               (I["C"] <= I["bbl"]))
        ext = I["e20"] > I["e50"]
    ent = (ent & I["liq"] & universe).fillna(False).astype(bool)
    return ent, ext.fillna(False).astype(bool)


def rs_rank(P, universe):
    C = P["Close"].ffill(limit=5)
    BM = P["BM"].ffill(limit=5)
    rs6 = (C / C.shift(126)).div(BM / BM.shift(126), axis=0)
    return rs6.where(universe).rank(axis=1, pct=True) * 100


# ================================================================== trades
def simulate_exit(P, ent, ext, rs, start, overlap=True, side=1):
    """Every signal day = a candidate (overlap) with its own exit: first
    close with the exit condition after entry -> next open."""
    O = P["Open"].values
    X = ext.values
    cal = P["Close"].index
    n = len(cal)
    first = cal.searchsorted(pd.Timestamp(start))
    rows = []
    for j, sym in enumerate(P["Close"].columns):
        hits = np.flatnonzero(ent.values[:, j])
        hits = hits[hits >= first]
        busy = -1
        for k in hits:
            if k <= busy or k + 1 >= n or not O[k + 1, j] > 0:
                continue
            e = O[k + 1, j]
            kx, px, why = n - 1, None, "open"
            for t in range(k + 1, n):
                if X[t, j] and t + 1 < n:
                    kx, px = bt._next_open(O, t + 1, j, n)
                    why = "signal"
                    break
            if kx is None or px is None:
                kx, px, why = n - 1, float(P["Close"].iloc[-1, j]), "open"
            r = side * (px / e - 1)
            rows.append({"col": j, "k_sig": k, "k_in": k + 1, "k_out": kx,
                         "symbol": sym.upper(), "signal": cal[k].date(),
                         "rs": float(rs.values[k, j]) if rs is not None
                         else np.nan, "entry": e, "exit": px, "why": why,
                         "bars": kx - k - 1, "ret": r, "side": side})
            if not overlap:
                busy = kx
    return pd.DataFrame(rows)


def trade_stats(t, col="ret", cost_rt=0.005):
    r = (t[col] - cost_rt).dropna()
    if not len(r):
        return {}
    w, l = r[r > 0], r[r <= 0]
    return {"trades": len(r), "win%": 100 * len(w) / len(r),
            "avg%": 100 * r.mean(), "median%": 100 * r.median(),
            "PF": w.sum() / -l.sum() if l.sum() < 0 else np.inf,
            "avg_win%": 100 * w.mean() if len(w) else 0,
            "avg_loss%": 100 * l.mean() if len(l) else 0,
            "hold_days": t.bars.median() * 7 / 5}


# ================================================================== tax book
class TaxBook:
    """Indian tax on realised gains, paid every 31 March."""

    def __init__(self, fno=False):
        self.fno = fno
        self.reset()
        self.cf_st = self.cf_lt = self.cf_bus = 0.0
        self.paid = 0.0

    def reset(self):
        self.st = self.lt = self.bus = self.interest = 0.0

    def add(self, gain, days):
        if self.fno:
            self.bus += gain
        elif days > 365:
            self.lt += gain
        else:
            self.st += gain

    def settle(self):
        tax = 0.0
        if self.fno:
            b = self.bus - self.cf_bus
            if b > 0:
                tax += SLAB * b
                self.cf_bus = 0.0
            else:
                self.cf_bus = -b
        else:
            st, lt = self.st, self.lt
            # current-year set-off: short-term loss vs any gain, long-term
            # loss vs long-term gain only
            if st < 0:
                lt, st = lt + st, 0.0
                if lt < 0:
                    self.cf_st += -lt
                    lt = 0.0
            if lt < 0:
                self.cf_lt += -lt
                lt = 0.0
            # brought-forward losses
            use = min(self.cf_st, st)
            st -= use
            self.cf_st -= use
            use = min(self.cf_st, lt)
            lt -= use
            self.cf_st -= use
            use = min(self.cf_lt, lt)
            lt -= use
            self.cf_lt -= use
            tax += STCG * st + LTCG * max(0.0, lt - LTCG_FREE)
        tax += SLAB * max(0.0, self.interest)
        self.paid += tax
        self.reset()
        return tax


def _fy_end(cal, t, n):
    """True on the last trading day of an Indian fiscal year (March) or on
    the last day of the test window (partial year is taxed too)."""
    return t + 1 >= n or (cal[t].month == 3 and cal[t + 1].month == 4)


# ================================================================== cash sim
def run_cash(P, cand, slots, start_k, end_k=None, capital=CAPITAL,
             real=True, tax=True, cash_rate=CASH_RATE, flat_cost=0.0025,
             exit_key=("k_out", "exit")):
    """Daily cash portfolio in rupees. Entries ranked by RS, equal slots,
    one position per stock. real=True uses Dhan costs + slippage + DP;
    real=False uses a flat % per side (to reproduce old tests)."""
    Cc = P["Close"].ffill().values
    cal = P["Close"].index
    n = len(cal) if end_k is None else end_k
    ko, po = exit_key
    c = cand[(cand.k_in >= start_k) & (cand.k_in < n)]
    by_day = {k: g.sort_values("rs", ascending=False)
              for k, g in c.groupby("k_in")}
    cash, pos = capital, {}
    book = TaxBook(False)
    day_rate = (1 + cash_rate) ** (1 / 252) - 1
    eq = np.full(n, np.nan)
    trades = 0

    def sell(col, px, t):
        nonlocal cash, trades
        p = pos.pop(col)
        gross = p["sh"] * px
        if real:
            fee = gross * (CASH_SELL + CASH_SLIP) + DP_CHARGE
        else:
            fee = gross * flat_cost
        cash += gross - fee
        book.add(gross - fee - p["basis"], (cal[t] - cal[p["k_in"]]).days)
        trades += 1

    for t in range(start_k, n):
        intr = cash * day_rate if cash > 0 else 0.0
        cash += intr
        book.interest += intr
        for col in [cc for cc, p in pos.items() if p["k_out"] <= t]:
            px = pos[col]["px"]
            sell(col, px if px is not None and px > 0 else Cc[t, col], t)
        if t in by_day and len(pos) < slots:
            mark = cash + sum(p["sh"] * Cc[t - 1, cc] for cc, p in pos.items())
            for r in by_day[t].itertuples():
                if len(pos) >= slots:
                    break
                if r.col in pos:
                    continue
                amt = min(mark / slots, cash)
                if amt < 1000:
                    break
                fee_pct = (CASH_BUY + CASH_SLIP) if real else flat_cost
                sh = amt / (r.entry * (1 + fee_pct))
                cash -= amt
                kx = getattr(r, ko)
                px = getattr(r, po)
                if kx >= n:
                    kx, px = n - 1, None
                pos[r.col] = {"sh": sh, "k_out": kx, "px": px, "k_in": t,
                              "basis": amt}
        if t == n - 1:                       # sell everything on the last day
            for col in list(pos):
                sell(col, Cc[t, col], t)
        if tax and _fy_end(cal, t, n):
            cash -= book.settle()
        eq[t] = cash + sum(p["sh"] * Cc[t, cc] for cc, p in pos.items())
    return pd.Series(eq[start_k:n], index=cal[start_k:n]), trades, book.paid


# ================================================================== futures
class FutBook:
    """Futures prices per (symbol, expiry) and the active contract per day."""

    def __init__(self, fut, cal):
        self.cal = cal
        f = fut[fut.kind == "STK"].copy()
        f["open"] = f["open"].where(f["open"] > 0, f["close"])
        f["close"] = f["close"].where(f["close"] > 0, f["settle"])
        self.px = {}
        f["k"] = cal.get_indexer(f["date"])
        f = f[f["k"] >= 0]
        for (s, e), g in f.groupby(["symbol", "expiry"], sort=False):
            k = g["k"].values
            lo = k.min()
            o = np.full(k.max() - lo + 1, np.nan)
            c = o.copy()
            o[k - lo] = g["open"].values
            c[k - lo] = g["close"].values
            self.px[(s, e)] = (lo, o, c)
        f = f[f.expiry >= f.date]
        k_exp = cal.searchsorted(f.expiry)
        k_day = cal.searchsorted(f.date)
        f["tdays"] = k_exp - k_day
        f = f.sort_values(["symbol", "date", "expiry"])
        near = f.groupby(["symbol", "date"]).nth(0)
        nxt = f.groupby(["symbol", "date"]).nth(1)
        near = near.set_index(["symbol", "date"])
        nxt = nxt.set_index(["symbol", "date"])["expiry"]
        act = near["expiry"].where(near["tdays"] > ROLL_DAYS,
                                   nxt.reindex(near.index))
        act = act.fillna(near["expiry"])
        self.active = act.unstack("symbol").reindex(cal)
        self.member = self.active.notna()

    def price(self, sym, exp, t, which):
        a = self.px.get((sym, exp))
        if a is None:
            return np.nan
        i = t - a[0]
        if i < 0 or i >= len(a[1]):
            return np.nan
        return a[1][i] if which == "open" else a[2][i]


def run_futures(P, fb, cand, slots, start_k, end_k=None, capital=CAPITAL,
                lev=1.0, tax=True, cash_rate=CASH_RATE):
    """Daily futures portfolio: notional per slot = equity x lev / slots,
    marked to market daily on the held contract, rolled 3 sessions before
    expiry, collateral earns cash_rate. Long and short candidates allowed."""
    cal = P["Close"].index
    n = len(cal) if end_k is None else end_k
    spot = P["Close"].ffill().values
    spot_open = P["Open"].values
    cols = list(P["Close"].columns)
    c = cand[(cand.k_in >= start_k) & (cand.k_in < n)]
    by_day = {k: g.sort_values("rs", ascending=False)
              for k, g in c.groupby("k_in")}
    cash, pos = capital, {}
    book = TaxBook(True)
    day_rate = (1 + cash_rate) ** (1 / 252) - 1
    eq = np.full(n, np.nan)
    orders = 0
    margin_short_days = 0

    def fee(notional, buy):
        nonlocal orders
        orders += 1
        return FUT_BROK + notional * ((FUT_BUY if buy else FUT_SELL) + FUT_SLIP)

    for t in range(start_k, n):
        intr = cash * day_rate if cash > 0 else 0.0
        cash += intr
        book.interest += intr
        # rolls and exits at today's open
        for col in list(pos):
            p = pos[col]
            sym = p["sym"]
            op = fb.price(sym, p["exp"], t, "open")
            if not op > 0:
                op = p["last"]
            so = spot_open[t, col] / p["spot_last"] - 1 \
                if p["spot_last"] > 0 and spot_open[t, col] > 0 else op / p["last"] - 1
            if abs((op / p["last"] - 1) - so) > 0.15:   # split/bonus overnight
                pnl = p["side"] * p["qty"] * p["last"] * so
                p["qty"] = p["qty"] * p["last"] * (1 + so) / op
            else:
                pnl = p["side"] * p["qty"] * (op - p["last"])
            expired = pd.Timestamp(p["exp"]) < cal[t]
            exiting = p["k_out"] <= t or expired
            act = fb.active[sym].iloc[t] if sym in fb.active else None
            rolling = (not exiting) and act is not None and \
                act == act and act != p["exp"]
            if exiting or rolling or t == n - 1:
                cost = fee(p["qty"] * op, buy=p["side"] < 0)
                cash += pnl - cost
                book.add(pnl - cost, 0)
                if exiting or t == n - 1:
                    del pos[col]
                    continue
                nop = fb.price(sym, act, t, "open")
                if not nop > 0:
                    nop = fb.price(sym, act, t, "close")
                if not nop > 0:            # cannot roll -> close
                    del pos[col]
                    continue
                cost = fee(p["qty"] * nop, buy=p["side"] > 0)
                cash -= cost
                book.add(-cost, 0)
                p.update(exp=act, last=nop,
                         spot_last=spot_open[t, col] if spot_open[t, col] > 0
                         else spot[t - 1, col])
            else:
                cash += pnl
                book.add(pnl, 0)
                p["last"] = op
                p["spot_last"] = spot_open[t, col] if spot_open[t, col] > 0 \
                    else p["spot_last"]
        # entries at today's open
        equity = cash
        if t in by_day and len(pos) < slots and t < n - 1:
            for r in by_day[t].itertuples():
                if len(pos) >= slots:
                    break
                if r.col in pos:
                    continue
                sym = cols[r.col].upper()
                if sym not in fb.active:
                    continue
                exp = fb.active[sym].iloc[t]
                if exp != exp:
                    continue
                op = fb.price(sym, exp, t, "open")
                if not op > 0:
                    continue
                notional = equity * lev / slots
                if notional <= 0:
                    break
                qty = notional / op
                cost = fee(notional, buy=r.side > 0)
                cash -= cost
                book.add(-cost, 0)
                so_ = spot_open[t, r.col]
                pos[r.col] = {"sym": sym, "exp": exp, "qty": qty,
                              "side": r.side, "last": op, "k_out": r.k_out,
                              "spot_last": so_ if so_ > 0 else spot[t - 1, r.col]}
        # mark to market at the close
        need = 0.0
        for col, p in pos.items():
            cl = fb.price(p["sym"], p["exp"], t, "close")
            if not cl > 0:
                continue
            fr = cl / p["last"] - 1
            sr = spot[t, col] / p["spot_last"] - 1 if p["spot_last"] > 0 else fr
            if abs(fr - sr) > 0.15:            # split/bonus: contract adjusted
                pnl = p["side"] * p["qty"] * p["last"] * sr
                p["qty"] = p["qty"] * p["last"] * (1 + sr) / cl
            else:
                pnl = p["side"] * p["qty"] * (cl - p["last"])
            cash += pnl
            book.add(pnl, 0)
            p["last"], p["spot_last"] = cl, spot[t, col]
            need += MARGIN * p["qty"] * cl
        if need > cash:
            margin_short_days += 1
        if tax and _fy_end(cal, t, n):
            cash -= book.settle()
        eq[t] = cash
    return (pd.Series(eq[start_k:n], index=cal[start_k:n]), orders,
            book.paid, margin_short_days)


# ================================================================== report
def perf(e):
    e = e.dropna()
    if len(e) < 2 or e.iloc[0] <= 0:
        return {}
    yrs = (e.index[-1] - e.index[0]).days / 365.25
    end = max(e.iloc[-1], 1e-9)
    cagr = (end / e.iloc[0]) ** (1 / yrs) - 1
    dd = (e / e.cummax() - 1).min()
    return {"CAGR%": 100 * cagr, "maxDD%": 100 * dd,
            "final_Rs": e.iloc[-1]}


def nifty_curve(P, a, b, capital=CAPITAL, tax=True):
    bm = P["BM"].ffill().iloc[a:b]
    e = capital * bm / bm.iloc[0] * (1 - 0.001)          # ETF buy cost
    if tax:
        g = e.iloc[-1] - capital
        e.iloc[-1] -= LTCG * max(0.0, g - LTCG_FREE) if g > 0 else 0.0
    return e


def periods(cal):
    k0 = cal.searchsorted(pd.Timestamp(START))
    ks = cal.searchsorted(pd.Timestamp(SPLIT))
    return (("2013-19", k0, ks), ("2020-26", ks, None), ("FULL", k0, None))


def table(rows):
    d = pd.DataFrame(rows).set_index("strategy")
    return d.to_string(float_format=lambda x: "%.1f" % x)


# ================================================================== studies
def load_pit10k():
    m, asof, src = ds.fetch_mcap()
    mc = m.set_index(m.symbol.str.lower())["mcap_cr"]
    P = bt.load_panels(list(mc[mc >= bt.MIN_LOAD].index),
                       (pd.Timestamp(START) - pd.DateOffset(days=800))
                       .strftime("%Y-%m-%d"))
    last = P["Close"].ffill().iloc[-1]
    uni = (P["Close"].ffill(limit=5) * (mc.reindex(P["Close"].columns) / last)
           >= bt.MCAP_MIN)
    return P, uni


def cash_study(P, uni):
    cal = P["Close"].index
    print("\nComputing Fusion + Weinstein/TT signals on the >= Rs 10,000 Cr "
          "point-in-time universe ...")
    I = indicators(P)
    rs = rs_rank(P, uni)
    ent, ext = fusion_signals(I, uni, 1)
    fus = simulate_exit(P, ent, ext, rs, START, overlap=True)
    fus1 = simulate_exit(P, ent, ext, rs, START, overlap=False)
    sig, rsw, m150, m200 = bt.signals(P, uni)
    wtt = bt.simulate(P, sig, rsw, m150, m200, START, overlap=True)
    wtt1 = bt.simulate(P, sig, rsw, m150, m200, START, overlap=False)

    print("\n" + "=" * 78)
    print(" TRADES, one per stock at a time, 0.5% round-trip cost "
          "(>= Rs 10,000 Cr, 2013-2026)")
    print("=" * 78)
    rows = {"Fusion": trade_stats(fus1),
            "W+TT swing exit": trade_stats(wtt1, cost_rt=0),
            "W+TT investing exit": trade_stats(
                wtt1.assign(ret=wtt1.inv_ret, bars=wtt1.inv_bars), cost_rt=0)}
    print(pd.DataFrame(rows).T.to_string(float_format=lambda x: "%.1f" % x))
    for name, t, cst in (("Fusion", fus1, 0.005), ("W+TT swing", wtt1, 0)):
        y = t.assign(year=pd.to_datetime(t.signal).dt.year).groupby("year")
        print("  %-11s avg %% by entry year: %s" % (name, "  ".join(
            "%d:%+.0f" % (k, 100 * (g.ret.mean() - cst)) for k, g in y)))

    # candidates for the portfolio (every signal day, own exit)
    wtt_sw = wtt[["col", "k_sig", "k_in", "k_out", "entry", "exit", "rs"]]
    wtt_in = wtt[["col", "k_sig", "k_in", "k_iout", "entry", "inv_exit",
                  "rs"]].rename(columns={"k_iout": "k_out",
                                         "inv_exit": "exit"})
    fus_c = fus[["col", "k_sig", "k_in", "k_out", "entry", "exit", "rs"]]
    pooled = pd.concat([fus_c, wtt_in])
    strategies = [("Fusion", fus_c), ("W+TT swing exit", wtt_sw),
                  ("W+TT investing exit", wtt_in),
                  ("Fusion + W+TT(inv) pooled", pooled)]

    print("\n" + "=" * 78)
    print(" ENGINE CHECK vs the old chat (0.25%/side flat, no tax, cash 0%, "
          "20 slots)")
    print("=" * 78)
    P1 = bt.load_panels(list(ds.FALLBACK), (pd.Timestamp(START) -
                        pd.DateOffset(days=800)).strftime("%Y-%m-%d"))
    u1 = P1["Close"].notna()
    I1 = indicators(P1)
    e1, x1 = fusion_signals(I1, u1, 1)
    c1 = simulate_exit(P1, e1, x1, rs_rank(P1, u1), START, overlap=True)
    k1 = P1["Close"].index.searchsorted(pd.Timestamp(START))
    p = perf(run_cash(P1, c1, 20, k1, real=False, tax=False, cash_rate=0)[0])
    print("  Fusion on the old 173 survivors : CAGR %5.1f%%, max DD %5.1f%%  "
          "(old chat: 17.4%%, -25.3%%)" % (p["CAGR%"], p["maxDD%"]))
    k0 = cal.searchsorted(pd.Timestamp(START))
    e, _, _ = run_cash(P, fus_c, 20, k0, real=False, tax=False, cash_rate=0)
    p = perf(e)
    print("  Fusion on >= Rs 10k point-in-time: CAGR %5.1f%%, max DD %5.1f%%"
          % (p["CAGR%"], p["maxDD%"]))

    out = {}
    for slots in (20, 8, 5):
        print("\n" + "=" * 78)
        print(" CASH PORTFOLIO, Rs 2 lakh, %d slots, real Dhan costs + "
              "slippage, idle cash 6%%" % slots)
        print("=" * 78)
        rows = []
        for name, c in strategies + [("NIFTY 50 (ETF, price only)", None)]:
            row = {"strategy": name}
            for tag, a, b in periods(cal):
                if c is None:
                    pre, post = nifty_curve(P, a, b, tax=False), \
                        nifty_curve(P, a, b, tax=True)
                    trades = 1
                else:
                    pre, trades, _ = run_cash(P, c, slots, a, b, tax=False)
                    post, _, _ = run_cash(P, c, slots, a, b, tax=True)
                pp, pt = perf(pre), perf(post)
                row[tag + " pre"] = pp.get("CAGR%")
                row[tag + " post-tax"] = pt.get("CAGR%")
                if tag == "FULL":
                    row["FULL maxDD"] = pp.get("maxDD%")
                    row["trades"] = trades
                    row["final Rs lakh"] = pt.get("final_Rs", np.nan) / 1e5
                    out[(slots, name)] = post
            rows.append(row)
        print(table(rows))
    robustness(P, strategies)
    return out


def robustness(P, strategies, sims=40):
    """Slot luck: same candidates, but the order among same-day signals is
    random instead of RS. If the real result sits far above the random
    median, the ranking matters; if it sits near the top, it was luck."""
    cal = P["Close"].index
    k0 = cal.searchsorted(pd.Timestamp(START))
    rng = np.random.default_rng(42)
    print("\n" + "=" * 78)
    print(" SLOT-LUCK CHECK: %d runs with RANDOM order among same-day signals "
          "(FULL period, pre-tax CAGR %%)" % sims)
    print("=" * 78)
    rows = []
    for slots in (20, 8, 5):
        for name, c in strategies[:3]:
            real = perf(run_cash(P, c, slots, k0, tax=False)[0])["CAGR%"]
            r = []
            for _ in range(sims):
                cc = c.assign(rs=rng.random(len(c)))
                r.append(perf(run_cash(P, cc, slots, k0, tax=False)[0])
                         ["CAGR%"])
            r = np.array(r)
            rows.append({"strategy": "%s, %d slots" % (name, slots),
                         "RS-ranked": real, "random p10": np.percentile(r, 10),
                         "random median": np.median(r),
                         "random p90": np.percentile(r, 90),
                         "worst": r.min(), "best": r.max()})
    print(table(rows))


def fno_study(P_cash, uni_cash):
    import fno_data
    fut = fno_data.load_futures()
    if fut.empty:
        print("\nNo F&O data -- run: python3 fno_data.py")
        return
    # spot history for EVERY stock that ever had futures (not only today's
    # big caps), so fallen F&O names stay in the test
    syms = sorted(fut[fut.kind == "STK"].symbol.str.lower().unique())
    P_all = bt.load_panels(syms, str(P_cash["Close"].index[0].date()))
    cal = P_all["Close"].index
    fut = fut[(fut.date >= cal[0]) & (fut.date <= cal[-1])]
    print("\nBuilding the futures book (%d rows, %d symbols) ..."
          % (len(fut), fut[fut.kind == "STK"].symbol.nunique()))
    fb = FutBook(fut, cal)
    cols_u = [c.upper() for c in P_all["Close"].columns]
    have = [s for s in fb.active.columns if s in set(cols_u)]
    miss = sorted(set(fb.active.columns) - set(have))
    print("  F&O symbols with spot history: %d | without (renamed/delisted, "
          "dropped): %d" % (len(have), len(miss)))
    keep = [c for c, u in zip(P_all["Close"].columns, cols_u) if u in have]
    P = {k: (v[keep] if isinstance(v, pd.DataFrame) else v)
         for k, v in P_all.items()}
    uni = fb.member[[c.upper() for c in keep]].copy()
    uni.columns = keep
    uni = uni.reindex(cal).fillna(False).astype(bool)
    size = uni.sum(axis=1)
    print("  F&O universe size by year: " + ", ".join(
        "%d:%d" % (y, v) for y, v in size.groupby(size.index.year).mean()
        .round().items() if y >= 2013))

    I = indicators(P)
    rs = rs_rank(P, uni)
    ent_l, ext_l = fusion_signals(I, uni, 1)
    ent_s, ext_s = fusion_signals(I, uni, -1)
    # only enter if a futures contract exists tomorrow
    nxt = uni.shift(-1).fillna(False).astype(bool)
    ent_l, ent_s = ent_l & nxt, ent_s & nxt
    lc = simulate_exit(P, ent_l, ext_l, rs, START, True, 1)
    sc = simulate_exit(P, ent_s, ext_s, 100 - rs, START, True, -1)
    l1 = simulate_exit(P, ent_l, ext_l, rs, START, False, 1)
    s1 = simulate_exit(P, ent_s, ext_s, 100 - rs, START, False, -1)

    print("\n" + "=" * 78)
    print(" F&O STOCKS -- Fusion trades on SPOT prices, one per stock, "
          "0.5% round trip")
    print("=" * 78)
    print(pd.DataFrame({"LONG": trade_stats(l1), "SHORT": trade_stats(s1)})
          .T.to_string(float_format=lambda x: "%.1f" % x))

    # Rs 2 lakh feasibility with REAL lot sizes
    print("\n" + "=" * 78)
    print(" CAN Rs 2 LAKH TRADE STOCK FUTURES? (real lot sizes, margin %.0f%%)"
          % (MARGIN * 100))
    print("=" * 78)
    f = fut[(fut.kind == "STK")].copy()
    f["value"] = f.lot * f.close.where(f.close > 0, f.settle)
    f = f.sort_values("expiry").groupby(["date", "symbol"]).first()
    f = f.reset_index()
    f["year"] = f.date.dt.year
    feas = f.groupby("year").agg(
        median_lot_value_lakh=("value", lambda x: x.median() / 1e5),
        median_margin_1lot_lakh=("value", lambda x: MARGIN * x.median() / 1e5),
        pct_stocks_1lot_margin_le_2L=("value", lambda x: 100 * (
            MARGIN * x <= CAPITAL).mean()),
        pct_stocks_4lots_le_2L=("value", lambda x: 100 * (
            4 * MARGIN * x <= CAPITAL).mean()))
    print(feas.to_string(float_format=lambda x: "%.1f" % x))

    rows = []
    variants = [
        ("Cash: Fusion on F&O stocks, 20 slots", "cash", lc, 20, 1.0),
        ("Futures LONG 1x, 20 slots", "fut", lc, 20, 1.0),
        ("Futures LONG 2x, 20 slots", "fut", lc, 20, 2.0),
        ("Futures SHORT only 1x, 20 slots", "fut", sc, 20, 1.0),
        ("Futures LONG+SHORT 1x, 20 slots", "fut", pd.concat([lc, sc]), 20,
         1.0),
        ("Futures LONG 1x, 5 slots", "fut", lc, 5, 1.0),
    ]
    print("\n" + "=" * 78)
    print(" F&O PORTFOLIO, real futures prices + rolls + costs, collateral "
          "6%, tax 31.2% (business income)")
    print(" (fractional lots -- see the table above for what Rs 2 lakh "
          "really allows)")
    print("=" * 78)
    for name, kind, c, slots, lev in variants + [("NIFTY 50 (ETF, price only)",
                                                   "nifty", None, 0, 0)]:
        row = {"strategy": name}
        for tag, a, b in periods(cal):
            if kind == "nifty":
                pre, post = nifty_curve(P, a, b, tax=False), \
                    nifty_curve(P, a, b, tax=True)
                extra = ""
            elif kind == "cash":
                pre, _, _ = run_cash(P, c, slots, a, b, tax=False)
                post, _, _ = run_cash(P, c, slots, a, b, tax=True)
                extra = ""
            else:
                pre, orders, _, mdays = run_futures(P, fb, c, slots, a, b,
                                                    lev=lev, tax=False)
                post, _, _, _ = run_futures(P, fb, c, slots, a, b, lev=lev,
                                            tax=True)
                extra = mdays
            pp, pt = perf(pre), perf(post)
            row[tag + " pre"] = pp.get("CAGR%")
            row[tag + " post-tax"] = pt.get("CAGR%")
            if tag == "FULL":
                row["FULL maxDD"] = pp.get("maxDD%")
                row["days margin short"] = extra if extra != "" else np.nan
        rows.append(row)
        print("  done: " + name)
    print(table(rows))


def main():
    a = sys.argv[1:]
    P, uni = load_pit10k()
    cash_study(P, uni)
    if "--cash-only" not in a:
        fno_study(P, uni)
    print("\nCosts: cash buy %.3f%% + sell %.3f%% + DP Rs %.2f + slippage "
          "%.2f%%/side | futures Rs %.0f/order + %.4f%%/%.4f%% + slippage "
          "%.2f%%/side" % (100 * CASH_BUY, 100 * CASH_SELL, DP_CHARGE,
                           100 * CASH_SLIP, FUT_BROK, 100 * FUT_BUY,
                           100 * FUT_SELL, 100 * FUT_SLIP))
    print("Delisted stocks are missing -> every strategy looks a bit too good.")


if __name__ == "__main__":
    main()
