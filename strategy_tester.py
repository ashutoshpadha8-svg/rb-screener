#!/usr/bin/env python3
"""
STRATEGY TESTER (6 Oct 2026, RB: "mujhe ek file mein do sab, taaki main khud
test kar sakoon"). ONE command, your own settings, same honest engine as
all the research (strategy_lab.run_rank): RAMOM momentum rank, >= Rs 10,000
Cr point-in-time universe + Rs 5 Cr liquidity, whole shares, real Dhan costs
+ 0.1% slippage, STCG/LTCG tax, idle cash 6%, Rs 2 lakh, 2013-01..2026-09.
Judged like every study: 2013-19 AND 2020-26 separately. An idea is better
only if it beats LIVE in BOTH halves.

Examples (run from ~/RB_Screener):
  python3 strategy_tester.py                         # = LIVE rule
  python3 strategy_tester.py --slots 10 --freq W     # weekly top 10
  python3 strategy_tester.py --sl 10                 # + 10% stop-loss
  python3 strategy_tester.py --trail 15              # + 15% trailing SL
  python3 strategy_tester.py --target 30             # sell at +30%
  python3 strategy_tester.py --slots 5 --buy-top 5 --freq D --sl 10
  python3 strategy_tester.py --mix none --keep 30    # no cap mix, sell rank>30
  python3 strategy_tester.py --mix 50/30/20          # Mid/Large/Small %

Settings (default = LIVE):
  --slots N        stocks held (20)
  --freq M|W|D     check ranking monthly / weekly / daily (M)
  --keep K         keep while rank <= K, sell above (40)
  --buy-top T      buy only stocks ranked 1..T (off = fill from the ranking)
  --sl P           fixed stop P% below the buy price (off)
  --trail P        trailing stop P% below the highest close (off)
  --target P       sell when the price touches +P% (off)
  --mix M/L/S      Mid/Large/Small % of slots (60/25/15), 'none' = rank only
  --sector-cap C   max stocks per industry (4), 0 = off
  --capital RS     start money (200000)
  --no-live        skip the LIVE comparison row (faster)
Every result is also appended to data/strategy_tests.csv. No orders, ever.
"""
import argparse
import datetime as dt
import os
import sys
import warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import daily_screener as ds                                    # noqa: E402
import fusion_backtest as fb                                   # noqa: E402
import strategy_lab as sl                                      # noqa: E402
import cap_mix_study as cm                                     # noqa: E402

LOG = os.path.join(ds.DATA, "strategy_tests.csv")


def mix_targets(txt, n):
    """'60/25/15' -> {'M': 12, 'L': 5, 'S': 3} for n=20 (sums to n)."""
    if str(txt).lower() in ("none", "off", "0"):
        return None
    p = [float(x) for x in str(txt).split("/")]
    if len(p) != 3 or abs(sum(p) - 100) > 0.5:
        sys.exit("--mix needs Mid/Large/Small %% adding to 100, e.g. 60/25/15")
    t = {"M": int(round(n * p[0] / 100)), "L": int(round(n * p[1] / 100)),
         "S": int(round(n * p[2] / 100))}
    t["M"] += n - sum(t.values())            # rounding leftover -> Mid
    return t


def describe(a):
    s = "%s top%d keep<=%d" % ({"M": "monthly", "W": "weekly",
                                 "D": "daily"}[a.freq], a.slots, a.keep)
    for k, lab in (("buy_top", "buy rank<=%g"), ("sl", "SL %g%%"),
                   ("trail", "trail %g%%"), ("target", "target +%g%%")):
        if getattr(a, k):
            s += ", " + lab % getattr(a, k)
    s += ", mix " + a.mix + (", sector cap %d" % a.sector_cap
                             if a.sector_cap else ", no sector cap")
    return s


def run(P, S, sector, cls, a, label):
    tg = mix_targets(a.mix, a.slots)
    kw = dict(sector=sector if a.sector_cap else None,
              sector_cap=a.sector_cap or None,
              cap_class=cls if tg else None, cap_targets=tg,
              buffer=a.keep / float(a.slots), capital=a.capital,
              buy_within=a.buy_top or None,
              stop_pct=a.sl / 100.0 if a.sl else None,
              trail_pct=a.trail / 100.0 if a.trail else None,
              target=a.target / 100.0 if a.target else None)
    cal = P["Close"].index
    r = {"test": label}
    for tag, s0, s1 in fb.periods(cal):
        st = {}
        pre, tr = sl.run_rank(P, S, a.slots, s0, s1, a.freq, tax=False,
                              stats=st, **kw)
        post, _ = sl.run_rank(P, S, a.slots, s0, s1, a.freq, tax=True, **kw)
        sl._fill(r, tag, pre, post, tr, cal)
        if tag == "FULL":
            r["worst yr %"] = post.resample("YE").last().pct_change().min() \
                * 100
            yrs = (pre.index[-1] - pre.index[0]).days / 365.25
            r["SL sells/yr"] = st.get("stop_exits", 0) / yrs
            r["target sells/yr"] = st.get("target_exits", 0) / yrs
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--slots", type=int, default=20)
    ap.add_argument("--freq", choices=["M", "W", "D"], default="M")
    ap.add_argument("--keep", type=int, default=40)
    ap.add_argument("--buy-top", type=int, default=0)
    ap.add_argument("--sl", type=float, default=0)
    ap.add_argument("--trail", type=float, default=0)
    ap.add_argument("--target", type=float, default=0)
    ap.add_argument("--mix", default="60/25/15")
    ap.add_argument("--sector-cap", type=int, default=4)
    ap.add_argument("--capital", type=float, default=200000)
    ap.add_argument("--no-live", action="store_true")
    a = ap.parse_args()
    if a.keep < a.slots:
        sys.exit("--keep must be >= --slots")
    print("Loading price history (first run of the day downloads, ~2-5 "
          "min) ...")
    P, uni = fb.load_pit10k()
    I = fb.indicators(P)
    elig = (uni & I["liq"]).fillna(False)
    S, ok = sl.scores(P, elig)
    ind = pd.read_csv(os.path.join(ds.DATA, "_nse_industry.csv"))
    m = dict(zip(ind.Symbol.astype(str).str.lower(), ind.Industry))
    sector = np.array([m.get(c, "?") for c in P["Close"].columns],
                      dtype=object)
    cls = cm.cap_classes(P)
    rows = []
    mine = describe(a)
    live = argparse.Namespace(slots=20, freq="M", keep=40, buy_top=0, sl=0,
                              trail=0, target=0, mix="60/25/15",
                              sector_cap=4, capital=a.capital)
    is_live = describe(live) == mine
    if not a.no_live and not is_live:
        print("  running LIVE rule (comparison) ...", flush=True)
        rows.append(run(P, S["RAMOM"], sector, cls, live, "LIVE: " +
                        describe(live)))
    print("  running YOUR test: %s ..." % mine, flush=True)
    rows.append(run(P, S["RAMOM"], sector, cls, a,
                    ("LIVE: " if is_live else "YOURS: ") + mine))
    T = pd.DataFrame(rows).set_index("test")
    cols = ["2013-19 post-tax", "2020-26 post-tax", "FULL post-tax",
            "FULL pre", "maxDD", "worst yr %", "trades/yr", "final Rs lakh",
            "SL sells/yr", "target sells/yr"]
    T = T[[c for c in cols if c in T]]
    pd.set_option("display.width", 250)
    pd.set_option("display.max_colwidth", 70)
    print("\n" + T.T.to_string(float_format=lambda x: "%.1f" % x))
    if len(rows) == 2:
        L, Y = rows[0], rows[1]
        d1 = Y["2013-19 post-tax"] - L["2013-19 post-tax"]
        d2 = Y["2020-26 post-tax"] - L["2020-26 post-tax"]
        print("\nVs LIVE: 2013-19 %+.1f pts, 2020-26 %+.1f pts/yr, max "
              "girawat %.0f%% vs %.0f%%" % (d1, d2, Y["maxDD"], L["maxDD"]))
        print("VERDICT: " + ("dono halves mein BEHTAR -- dobara chalao, "
                             "phir Claude se live karne ki baat karo"
                             if d1 > 0 and d2 > 0 else
                             "dono halves mein behtar NAHI -> live rule "
                             "hi rakho"))
    print("(Backtest = past. Survivors-only data makes every row a bit too "
          "good. Info only, no orders.)")
    out = T.reset_index()
    out.insert(0, "run_at", dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
    out.to_csv(LOG, mode="a", header=not os.path.exists(LOG), index=False)
    print("Saved to %s" % LOG)


if __name__ == "__main__":
    main()
