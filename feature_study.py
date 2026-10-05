#!/usr/bin/env python3
"""
FEATURE STUDY (5 Oct 2026, RB: "research karo ki jo stocks ache chale unme
kya common tha, taki usi basis par filter kar sakein"). Large-sample version
of the 20-stock / 4-day ChatGPT look.

Sample: every month 2013-01..2026-09, the RAMOM top 20 (raw rank, same
eligible >= Rs 10k Cr + liquidity universe), bought at the rebalance-day
open. Outcome = 3-month (63 sessions) and 6-month (126) return MINUS the
median return of all eligible stocks over the same days (= excess).

Features are known at the previous close (no look-ahead). Inside each
month's 20 picks the feature splits them into 3 groups (low / mid / high);
spread = high-group avg excess - low-group avg excess, per month, averaged.
PRE-REGISTERED pass rule: the 3-month spread has the SAME sign in 2013-19
and 2020-26, is >= 2 pts in both, its month t-stat >= 2 in both, and the
6-month spread agrees in sign. Everything else = no reliable filter.
python3 feature_study.py
"""
import warnings
warnings.filterwarnings("ignore")
import os
import sys
import numpy as np
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fusion_backtest as fb                                   # noqa: E402
import strategy_lab as sl                                      # noqa: E402

TOP, H3, H6 = 20, 63, 126


def wilder(x, n):
    return x.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def features(P):
    C = P["Close"].ffill(limit=5)
    H, L, V = P["High"], P["Low"], P["Volume"]
    d = C.diff()
    rsi = 100 - 100 / (1 + wilder(d.clip(lower=0), 14) /
                       wilder((-d).clip(lower=0), 14))
    tr = pd.concat([H - L, (H - C.shift()).abs(), (L - C.shift()).abs()]) \
        .groupby(level=0).max() if False else np.maximum(
            H - L, np.maximum((H - C.shift()).abs(), (L - C.shift()).abs()))
    atr = wilder(tr, 14)
    e20 = C.ewm(span=20, adjust=False).mean()
    ma50, ma200 = C.rolling(50).mean(), C.rolling(200).mean()
    r = C.pct_change()
    F = {
        "RSI 14": rsi,
        "1-month return %": 100 * (C / C.shift(21) - 1),
        "1-week return % (pullback = low)": 100 * (C / C.shift(5) - 1),
        "6-month return %": 100 * (C / C.shift(126) - 1),
        "12-month return %": 100 * (C / C.shift(252) - 1),
        "Above EMA20 in ATRs (stretch)": (C - e20) / atr,
        "From 52w high %": 100 * (C / C.rolling(252).max() - 1),
        "Above 50 DMA %": 100 * (C / ma50 - 1),
        "200 DMA slope 1m %": 100 * (ma200 / ma200.shift(21) - 1),
        "ATR % (daily swing)": 100 * atr / C,
        "1-year volatility %": 100 * r.rolling(252).std() * np.sqrt(252),
        "Volume 5d / 60d": V.rolling(5).mean() / V.rolling(60).mean(),
        "Range 20d / 60d (tight = low)": (H.rolling(20).max() -
                                          L.rolling(20).min()) /
        (H.rolling(60).max() - L.rolling(60).min()),
        "Up-volume share 20d": (V.where(d > 0, 0).rolling(20).sum() /
                                V.rolling(20).sum()),
        "Close in day range (last day)": (C - L) / (H - L).replace(0, np.nan),
    }
    return F, C


def main():
    P, uni = fb.load_pit10k()
    cal = P["Close"].index
    I = fb.indicators(P)
    elig = (uni & I["liq"]).fillna(False)
    S, ok = sl.scores(P, elig)
    F, C = features(P)
    import cap_mix_study as cm
    cls = cm.cap_classes(P)
    O = P["Open"].values
    Cv = C.values
    E = elig.values
    sc = S["RAMOM"].values
    start = cal.searchsorted(pd.Timestamp("2013-01-01"))
    rows = []
    for t in sorted(sl.rebal_days(cal, start, len(cal) - H3)):
        s = sc[t - 1]
        valid = ~np.isnan(s)
        top = [j for j in np.argsort(-np.where(valid, s, -np.inf))
               if valid[j]][:TOP]
        pool = np.flatnonzero(E[t - 1] & (O[t] > 0))
        for h, lab in ((H3, "x3"), (H6, "x6")):
            if t + h - 1 >= len(cal):
                continue
            ret = Cv[t + h - 1] / O[t] - 1
            med = np.nanmedian(ret[pool])
            for j in top:
                if not O[t, j] > 0 or np.isnan(ret[j]):
                    continue
                key = (t, j)
                rows.append({"t": t, "j": j, "h": lab,
                             "excess": 100 * (ret[j] - med)})
    R = pd.DataFrame(rows).pivot_table(index=["t", "j"], columns="h",
                                       values="excess").reset_index()
    R["date"] = cal[R["t"]]
    R["half"] = np.where(R["date"].dt.year <= 2019, "2013-19", "2020-26")
    for name, f in F.items():
        R[name] = f.values[R["t"] - 1, R["j"]]
    R["Cap class"] = cls[R["t"] - 1, R["j"]]
    print("\nSample: %d picks in %d months (3m outcome), median 3m excess "
          "%+.1f%%, avg %+.1f%%" % (R["x3"].notna().sum(), R["t"].nunique(),
                                     R["x3"].median(), R["x3"].mean()))
    out = []
    for name in F:
        row = {"Feature": name}
        good = True
        signs = []
        for half in ("2013-19", "2020-26"):
            g = R[R.half == half].dropna(subset=[name])
            sp3, sp6, md3 = [], [], []
            for t, m in g.groupby("t"):
                if len(m) < 9:
                    continue
                q = pd.qcut(m[name].rank(method="first"), 3,
                            labels=[0, 1, 2])
                lo, hi = m[q == 0], m[q == 2]
                sp3.append(hi["x3"].mean() - lo["x3"].mean())
                md3.append(hi["x3"].median() - lo["x3"].median())
                if hi["x6"].notna().any() and lo["x6"].notna().any():
                    sp6.append(hi["x6"].mean() - lo["x6"].mean())
            sp3 = pd.Series(sp3).dropna()
            tstat = sp3.mean() / (sp3.std() / np.sqrt(len(sp3))) \
                if len(sp3) > 2 and sp3.std() > 0 else 0
            row["%s 3m spread" % half] = sp3.mean()
            row["%s t" % half] = tstat
            row["%s median spr" % half] = np.nanmean(md3)
            row["%s 6m spread" % half] = np.nanmean(sp6) if sp6 else np.nan
            signs.append((np.sign(sp3.mean()), abs(sp3.mean()), abs(tstat),
                          np.sign(np.nanmean(sp6)) if sp6 else 0))
        s0, s1 = signs
        good = (s0[0] == s1[0] != 0 and s0[1] >= 2 and s1[1] >= 2 and
                s0[2] >= 2 and s1[2] >= 2 and s0[3] == s0[0] and
                s1[3] == s1[0])
        row["PASS"] = ("YES: high better" if s0[0] > 0 else
                       "YES: low better") if good else "no"
        out.append(row)
    T = pd.DataFrame(out).set_index("Feature")
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 20)
    print("\nSpread = HIGH third minus LOW third of each month's 20 picks, "
          "avg 3-month excess vs universe (pct points). t = month t-stat.")
    print(T.to_string(float_format=lambda x: "%+.1f" % x))
    print("\nBy cap class (3m / 6m avg excess, median 3m, picks):")
    for half in ("2013-19", "2020-26"):
        g = R[R.half == half]
        for c in ("L", "M", "S"):
            x = g[g["Cap class"] == c]
            if len(x):
                print("  %s %s  3m %+.1f  6m %+.1f  median3m %+.1f  n=%d"
                      % (half, c, x["x3"].mean(), x["x6"].mean(),
                         x["x3"].median(), len(x)))
    R.to_csv(os.path.join(HERE, "data", "feature_study_picks.csv"),
             index=False)
    T.to_csv(os.path.join(HERE, "data", "feature_study_result.csv"))


if __name__ == "__main__":
    main()
