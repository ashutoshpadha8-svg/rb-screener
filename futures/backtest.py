"""
Futures intraday backtester with Topstep 50K Combine rules.

Data: Dukascopy 1-minute index CFD bars (US 500 / US Tech 100) as a proxy for MES / MNQ.
Download (needs Node.js):
  npx dukascopy-node -i usa500idxusd  -from 2016-01-01 -to 2026-09-26 -t m1 -f csv -dir data
  npx dukascopy-node -i usatechidxusd -from 2016-01-01 -to 2026-09-26 -t m1 -f csv -dir data

Run:
  python3 backtest.py data/usa500idxusd-m1-bid-2016-01-01-2026-09-26.csv MES

Strategies (parameters taken from the papers, NOT optimised):
  NOISE  - intraday momentum / noise-area breakout (Zarattini, Aziz, Barbon 2024)
  ORB5   - 5-min opening range, trade in direction of first candle (Zarattini & Aziz 2023)
  ORB30  - 30-min opening range breakout, stop at other side of range
  LAST30 - first-30-min return predicts last 30 min (Gao, Han, Li, Zhou 2018)
  VWAPMR - fade 2-sigma stretch from VWAP after 10:30, target VWAP (comparison only)
"""
import sys

import numpy as np
import pandas as pd

# ---------------- settings ----------------
SPECS = {  # point value $, tick size
    "MES": (5.0, 0.25),
    "MNQ": (2.0, 0.25),
}
COMMISSION_PER_SIDE = 0.75   # $ per micro contract per side (commission + exchange fees, approx)
SLIP_TICKS_PER_SIDE = 1      # 1 tick slippage on every entry and exit
RISK_PER_TRADE = 200.0       # $ risked per trade in Combine sim (10% of the $2,000 max loss)
MAX_MICROS = 50              # Topstep 50K = 5 minis = 50 micros
START_BAL = 50000.0
TARGET = 3000.0
MLL = 2000.0                 # end-of-day trailing max loss limit, locks at start balance
CONSISTENCY = 0.50           # best day must be < 50% of total profit to pass
IS_END = "2021-12-31"        # in-sample 2016-2021, out-of-sample 2022-2026


def load(path):
    df = pd.read_csv(path)
    ts = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_convert("America/New_York")
    df.index = ts
    df = df.drop(columns=["timestamp"])
    t = df.index.hour * 60 + df.index.minute
    df = df[(t >= 9 * 60 + 30) & (t < 16 * 60)].copy()   # regular session only
    df["date"] = df.index.date
    df["mod"] = df.index.hour * 60 + df.index.minute - (9 * 60 + 30)  # minute of day, 0..389
    return df


def day_table(df):
    """One row per session: arrays of minute bars aligned to 0..389."""
    days = []
    prev_close = np.nan
    for d, g in df.groupby("date"):
        if len(g) < 300:        # skip half days / broken data
            prev_close = g["close"].iloc[-1] if len(g) else prev_close
            continue
        full = g.set_index("mod")[["open", "high", "low", "close"]].reindex(range(390)).ffill().bfill()
        days.append({
            "date": pd.Timestamp(d),
            "o": full["open"].values, "h": full["high"].values,
            "l": full["low"].values, "c": full["close"].values,
            "prev_close": prev_close,
        })
        prev_close = full["close"].values[-1]
    return days


def vwap_proxy(day):
    # no volume in the data -> use cumulative average of typical price (TWAP) as VWAP proxy
    tp = (day["h"] + day["l"] + day["c"]) / 3.0
    return np.cumsum(tp) / np.arange(1, len(tp) + 1)


# Each strategy returns a list of trades: dict(date, side, entry, exit, risk_pts, mae_pts)
# All prices are in index points; entries/exits at bar close unless a stop is hit.

def trade(date, side, entry, exit_, risk_pts, mae_pts):
    return {"date": date, "side": side, "entry": entry, "exit": exit_,
            "pts": side * (exit_ - entry), "risk_pts": risk_pts, "mae_pts": mae_pts}


def mae(day, side, entry, i0, i1):
    if i1 < i0:
        return 0.0
    if side > 0:
        return max(0.0, entry - day["l"][i0:i1 + 1].min())
    return max(0.0, day["h"][i0:i1 + 1].max() - entry)


def strat_noise(days, lookback=14):
    """Zarattini et al. 2024: band = open * (1 +/- avg |move from open| at this minute over last 14 days).
    Check every 30 min from 10:00. Long above upper band, short below lower. Trailing stop = band or VWAP.
    Flat at close."""
    out = []
    moves = []  # list of arrays |c/o - 1|
    for k, day in enumerate(days):
        o = day["o"][0]
        if len(moves) >= lookback and not np.isnan(day["prev_close"]):
            sigma = np.mean(moves[-lookback:], axis=0)
            ub = max(o, day["prev_close"]) * (1 + sigma)
            lb = min(o, day["prev_close"]) * (1 - sigma)
            vw = vwap_proxy(day)
            pos, entry, i_in, risk = 0, 0.0, 0, 0.0
            for i in range(30, 390, 30):          # 10:00, 10:30 ... 15:30 decision points
                c = day["c"][i - 1]
                if pos == 1 and c < max(ub[i - 1], vw[i - 1]):
                    out.append(trade(day["date"], 1, entry, c, risk, mae(day, 1, entry, i_in, i - 1))); pos = 0
                elif pos == -1 and c > min(lb[i - 1], vw[i - 1]):
                    out.append(trade(day["date"], -1, entry, c, risk, mae(day, -1, entry, i_in, i - 1))); pos = 0
                if pos == 0:
                    if c > ub[i - 1]:
                        pos, entry, i_in = 1, c, i
                        risk = c - max(ub[i - 1], vw[i - 1]) + 0.25 * sigma[i - 1] * c + 1
                    elif c < lb[i - 1]:
                        pos, entry, i_in = -1, c, i
                        risk = min(lb[i - 1], vw[i - 1]) - c + 0.25 * sigma[i - 1] * c + 1
            if pos != 0:
                out.append(trade(day["date"], pos, entry, day["c"][-1], risk, mae(day, pos, entry, i_in, 389)))
        moves.append(np.abs(day["c"] / o - 1))
    return out


def strat_orb5(days):
    """Zarattini & Aziz 2023: first 5-min candle direction; enter at 9:35 open; stop at other end of candle;
    no target, exit at close."""
    out = []
    for day in days:
        o5, c5 = day["o"][0], day["c"][4]
        h5, l5 = day["h"][:5].max(), day["l"][:5].min()
        if c5 == o5:
            continue
        side = 1 if c5 > o5 else -1
        entry = day["o"][5]
        stop = l5 if side > 0 else h5
        risk = side * (entry - stop)
        if risk <= 0:
            continue
        exit_, idx = day["c"][-1], 389
        for i in range(5, 390):
            if (side > 0 and day["l"][i] <= stop) or (side < 0 and day["h"][i] >= stop):
                exit_, idx = stop, i
                break
        out.append(trade(day["date"], side, entry, exit_, risk, mae(day, side, entry, 5, idx)))
    return out


def strat_orb30(days):
    """Break of 30-min opening range (first break only), stop at other side of range, exit at close."""
    out = []
    for day in days:
        hi, lo = day["h"][:30].max(), day["l"][:30].min()
        side, entry, i_in = 0, 0.0, 0
        for i in range(30, 390):
            if day["h"][i] > hi:
                side, entry, i_in = 1, hi, i; break
            if day["l"][i] < lo:
                side, entry, i_in = -1, lo, i; break
        if side == 0:
            continue
        stop = lo if side > 0 else hi
        risk = hi - lo
        exit_, idx = day["c"][-1], 389
        for i in range(i_in + 1, 390):
            if (side > 0 and day["l"][i] <= stop) or (side < 0 and day["h"][i] >= stop):
                exit_, idx = stop, i
                break
        out.append(trade(day["date"], side, entry, exit_, risk, mae(day, side, entry, i_in, idx)))
    return out


def strat_last30(days, lookback=14):
    """Gao et al. 2018: sign of (prev close -> 10:00) return; trade 15:30 -> 16:00 in that direction."""
    out = []
    hist = []
    for day in days:
        last_move = abs(day["c"][-1] - day["c"][359])
        if len(hist) >= lookback and not np.isnan(day["prev_close"]):
            r1 = day["c"][29] - day["prev_close"]
            if r1 != 0:
                side = 1 if r1 > 0 else -1
                entry, exit_ = day["c"][359], day["c"][-1]
                risk = 2 * np.mean(hist[-lookback:])  # sizing proxy, no hard stop
                out.append(trade(day["date"], side, entry, exit_, risk, mae(day, side, entry, 360, 389)))
        hist.append(last_move)
    return out


def strat_vwapmr(days, lookback=14):
    """Fade: after 10:30, if price is > 2x avg abs(close - VWAP) away from VWAP, fade it.
    Target VWAP, stop 1x further stretch, exit at close. One trade per day."""
    out = []
    hist = []
    for day in days:
        vw = vwap_proxy(day)
        dev = day["c"] - vw
        if len(hist) >= lookback:
            s = np.mean(hist[-lookback:])
            for i in range(60, 360):
                if abs(dev[i]) > 2 * s:
                    side = -1 if dev[i] > 0 else 1
                    entry = day["c"][i]
                    stop = entry - side * s
                    exit_, idx = day["c"][-1], 389
                    for j in range(i + 1, 390):
                        if (side > 0 and day["l"][j] <= stop) or (side < 0 and day["h"][j] >= stop):
                            exit_, idx = stop, j; break
                        if (side > 0 and day["h"][j] >= vw[j]) or (side < 0 and day["l"][j] <= vw[j]):
                            exit_, idx = vw[j], j; break
                    out.append(trade(day["date"], side, entry, exit_, s, mae(day, side, entry, i + 1, idx)))
                    break
        hist.append(np.mean(np.abs(dev)))
    return out


STRATS = {"NOISE": strat_noise, "ORB5": strat_orb5, "ORB30": strat_orb30,
          "LAST30": strat_last30, "VWAPMR": strat_vwapmr}


def to_dollars(trades, pv, tick):
    t = pd.DataFrame(trades)
    if t.empty:
        return t
    cost_pts = 2 * SLIP_TICKS_PER_SIDE * tick
    t["n"] = np.clip(np.floor(RISK_PER_TRADE / (t["risk_pts"] * pv)), 1, MAX_MICROS)
    t["pnl1"] = (t["pts"] - cost_pts) * pv - 2 * COMMISSION_PER_SIDE       # 1 micro
    t["pnl"] = t["pnl1"] * t["n"]                                          # sized
    t["mae"] = t["mae_pts"] * pv * t["n"]
    return t


def stats(t, col):
    p = t[col]
    wins, losses = p[p > 0], p[p <= 0]
    daily = t.groupby("date")[col].sum()
    eq = daily.cumsum()
    dd = (eq - eq.cummax()).min()
    pf = wins.sum() / -losses.sum() if losses.sum() != 0 else np.inf
    return {"trades": len(p), "win%": 100 * len(wins) / max(len(p), 1), "avg$": p.mean(),
            "PF": pf, "total$": p.sum(), "maxDD$": dd,
            "sharpe": daily.mean() / daily.std() * np.sqrt(252) if daily.std() > 0 else 0}


def combine_sim(t, all_dates):
    """Start a Combine on every 5th session; run until pass or blow. Returns pass%, fail%, median days."""
    daily_pnl = t.groupby("date")["pnl"].sum()
    daily_mae = t.groupby("date")["mae"].max()
    dates = list(all_dates)
    res = []
    for s in range(0, len(dates) - 60, 5):
        bal, peak_eod, best, days_n = START_BAL, START_BAL, 0.0, 0
        outcome = "open"
        for d in dates[s:]:
            days_n += 1
            floor = min(peak_eod - MLL, START_BAL)
            pnl = daily_pnl.get(d, 0.0)
            worst = daily_mae.get(d, 0.0)
            if bal - worst <= floor:          # intraday touch of max loss (approx, one trade/day)
                outcome = "fail"; break
            bal += pnl
            if bal <= floor:
                outcome = "fail"; break
            peak_eod = max(peak_eod, bal)
            best = max(best, pnl)
            profit = bal - START_BAL
            if profit >= TARGET and best < CONSISTENCY * profit and days_n >= 2:
                outcome = "pass"; break
        res.append((outcome, days_n))
    r = pd.DataFrame(res, columns=["outcome", "days"])
    done = r[r["outcome"] != "open"]
    return {"sims": len(done),
            "pass%": 100 * (done["outcome"] == "pass").mean() if len(done) else np.nan,
            "med_days_to_pass": done.loc[done["outcome"] == "pass", "days"].median()}


def main():
    path, sym = sys.argv[1], sys.argv[2]
    pv, tick = SPECS[sym]
    df = load(path)
    days = day_table(df)
    all_dates = [d["date"] for d in days]
    print("%s: %d sessions %s -> %s" % (sym, len(days), all_dates[0].date(), all_dates[-1].date()))
    rows = []
    for name, fn in STRATS.items():
        t = to_dollars(fn(days), pv, tick)
        if t.empty:
            continue
        for label, part in (("IS 2016-21", t[t["date"] <= IS_END]), ("OOS 2022-26", t[t["date"] > IS_END])):
            s1 = stats(part, "pnl1")
            dates = [d for d in all_dates if (d <= pd.Timestamp(IS_END)) == label.startswith("IS")]
            c = combine_sim(part, dates)
            rows.append({"strategy": name, "period": label, "trades": s1["trades"],
                         "win%": round(s1["win%"], 1), "avg$/1micro": round(s1["avg$"], 2),
                         "PF": round(s1["PF"], 2), "sharpe": round(s1["sharpe"], 2),
                         "total$/1micro": round(s1["total$"]), "maxDD$/1micro": round(s1["maxDD$"]),
                         "combine_pass%": round(c["pass%"], 1), "med_days": c["med_days_to_pass"]})
    out = pd.DataFrame(rows)
    pd.set_option("display.width", 200)
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
