"""
Backtest ICT / "smart money" ideas with fixed, pre-declared rules (no tuning):

  AMD_LDN  - Power of 3: Accumulation = Asia range (20:00-00:00 ET). Manipulation = London (02:00-05:00 ET)
             sweeps ONE side of the Asia range. Distribution = at 9:30 NY open trade the opposite way.
             Stop = London sweep extreme. Target 2R, else exit 15:59.
  AMD_NY   - Accumulation = overnight range (18:00-09:30). Manipulation = between 9:30-11:00 price trades beyond
             the overnight high/low and a 5-min bar closes back inside -> enter opposite way next bar.
             Stop = sweep extreme. Target 2R, else exit 15:59.
  SWEEP_PD - Liquidity sweep of previous day high/low (RTH), 9:30-13:00, same entry logic as AMD_NY.
  ..._EOD  - same entries but no 2R target: hold to 15:59 (lets winners run).

Order flow (footprint, delta, absorption) can NOT be tested here: it needs tick data with buy/sell aggressor
volume. This data is 1-minute price only.

Run:
  python3 smc_test.py data/usatechidxusd-m1-bid-2016-01-01-2026-09-26.csv MNQ
"""
import sys

import numpy as np
import pandas as pd

import backtest as bt

MAX_DAYS = 60
MIN_RISK_FRAC = 0.0003     # stop at least 0.03% of price away (NQ ~6 pts, ES ~1.5 pts)
RR = 2.0


def load_all(path):
    df = pd.read_csv(path)
    ts = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_convert("America/New_York").dt.tz_localize(None)
    return (ts.values.astype("datetime64[m]"), df["open"].values, df["high"].values,
            df["low"].values, df["close"].values)


def sl(t, a, b):
    """index slice [a, b) of sorted minute timestamps"""
    return np.searchsorted(t, a), np.searchsorted(t, b)


def run_trade(t, o, h, l, c, i, side, entry, stop, target, end_i):
    """walk bars from i until stop / target / end. Stop assumed first if both hit in one bar."""
    worst = 0.0
    for k in range(i, end_i):
        if side > 0:
            worst = max(worst, entry - l[k])
            if l[k] <= stop:
                return min(stop, o[k]), worst
            if target is not None and h[k] >= target:
                return target, worst
        else:
            worst = max(worst, h[k] - entry)
            if h[k] >= stop:
                return max(stop, o[k]), worst
            if target is not None and l[k] <= target:
                return target, worst
    return c[end_i - 1], worst


def sweep_reversal(t, o, h, l, c, i0, i1, hi, lo, end_i):
    """In window [i0, i1): price trades beyond hi (or lo); first 5-min bar close back inside -> reversal entry."""
    swept_hi = swept_lo = False
    ext_hi, ext_lo = -np.inf, np.inf
    for k in range(i0, i1 - 5, 5):
        bh, bl, bc = h[k:k + 5].max(), l[k:k + 5].min(), c[k + 4]
        if bh > hi:
            swept_hi = True
            ext_hi = max(ext_hi, bh)
        if bl < lo:
            swept_lo = True
            ext_lo = min(ext_lo, bl)
        if swept_hi and swept_lo:
            return None                     # both sides taken - no clean manipulation
        if swept_hi and bc < hi:
            return -1, k + 5, ext_hi
        if swept_lo and bc > lo:
            return 1, k + 5, ext_lo
    return None


def strategies(t, o, h, l, c):
    days = pd.to_datetime(np.unique(t.astype("datetime64[D]")))
    out = {k: [] for k in ["AMD_LDN", "AMD_LDN_EOD", "AMD_NY", "AMD_NY_EOD", "SWEEP_PD", "SWEEP_PD_EOD"]}
    prev_rth = None
    for d in days:
        if d.weekday() >= 5:
            continue
        D = np.datetime64(d.date(), "m")
        r0, r1 = sl(t, D + 570, D + 960)            # 09:30-16:00
        if r1 - r0 < 300:
            continue
        a0, a1 = sl(t, D - 240, D)                  # Asia 20:00-00:00 (previous evening)
        n0, n1 = sl(t, D + 120, D + 300)            # London 02:00-05:00
        o0, o1 = sl(t, D - 360, D + 570)            # overnight 18:00-09:30
        day_rows = []

        def add(name, side, i, entry, stop, target_ok=True):
            risk = side * (entry - stop)
            risk = max(risk, MIN_RISK_FRAC * entry)
            stop = entry - side * risk
            for suffix, tgt in (("", entry + side * RR * risk), ("_EOD", None)):
                ex, worst = run_trade(t, o, h, l, c, i, side, entry, stop, tgt, r1)
                out[name + suffix].append(bt.trade(d, side, entry, ex, risk, worst))

        # AMD_LDN
        if a1 - a0 > 100 and n1 - n0 > 100:
            ahi, alo = h[a0:a1].max(), l[a0:a1].min()
            lhi, llo = h[n0:n1].max(), l[n0:n1].min()
            if (lhi > ahi) != (llo < alo):          # exactly one side swept
                side = -1 if lhi > ahi else 1
                stop = lhi if side < 0 else llo
                entry = o[r0]
                if side * (entry - stop) > 0:
                    add("AMD_LDN", side, r0, entry, stop)
        # AMD_NY
        if o1 - o0 > 300:
            ohi, olo = h[o0:o1].max(), l[o0:o1].min()
            k1 = np.searchsorted(t, D + 660)        # 11:00
            s = sweep_reversal(t, o, h, l, c, r0, k1, ohi, olo, r1)
            if s:
                side, i, ext = s
                add("AMD_NY", side, i, o[i], ext)
        # SWEEP_PD
        if prev_rth is not None:
            k1 = np.searchsorted(t, D + 780)        # 13:00
            s = sweep_reversal(t, o, h, l, c, r0, k1, prev_rth[0], prev_rth[1], r1)
            if s:
                side, i, ext = s
                add("SWEEP_PD", side, i, o[i], ext)
        prev_rth = (h[r0:r1].max(), l[r0:r1].min())
    return out


def main():
    path, sym = sys.argv[1], sys.argv[2]
    pv, tick = bt.SPECS[sym]
    t, o, h, l, c = load_all(path)
    all_dates = sorted(set(pd.to_datetime(np.unique(t.astype("datetime64[D]")))))
    all_dates = [d for d in all_dates if d.weekday() < 5]
    d_is = [d for d in all_dates if d <= pd.Timestamp(bt.IS_END)]
    d_oos = [d for d in all_dates if d > pd.Timestamp(bt.IS_END)]
    bt.RISK_PER_TRADE = 250.0
    rows = []
    for name, trades in strategies(t, o, h, l, c).items():
        tr = bt.to_dollars(trades, pv, tick)
        for label, part, dates in (("IS 2016-21", tr[tr["date"] <= bt.IS_END], d_is),
                                   ("OOS 2022-26", tr[tr["date"] > bt.IS_END], d_oos)):
            s = bt.stats(part, "pnl")
            cmb = bt.combine_sim(part, dates, MAX_DAYS)
            z = part.copy()
            z["pnl"] = z["pnl"] - z["pnl"].mean()
            base = bt.combine_sim(z, dates, MAX_DAYS)
            rows.append({"strategy": name, "period": label, "trades": s["trades"], "win%": round(s["win%"], 1),
                         "avg$": round(s["avg$"], 1), "PF": round(s["PF"], 2), "sharpe": round(s["sharpe"], 2),
                         "total$": round(s["total$"]), "maxDD$": round(s["maxDD$"]),
                         "pass%": round(cmb["pass%"], 1), "luck%": round(base["pass%"], 1)})
    pd.set_option("display.width", 220)
    print("%s, $%.0f risk per trade, costs 1 tick + $0.75/side per micro" % (sym, bt.RISK_PER_TRADE))
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
