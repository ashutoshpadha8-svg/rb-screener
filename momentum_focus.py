"""
momentum_focus.py -- momentum rank 1-5 "look here first" (1 Oct 2026, RB
approved A+C of Codex's Top-5 highlight proposal). DISPLAY ONLY: no ranking,
selection, sizing, exit or order logic lives here, and nothing here talks to
a broker or an account.

  focus(ranks)          -> selected stocks with rank 1..5, best first
  load()                -> (focus rows, ranks date, message) from
                           data/momentum_ranks_latest.csv
  cohort(t)             -> how the momentum rank 1-5 FINDS did so far
                           (Signal_Tracker rows), with sample size + age
  cohort_line(c)        -> that as one honest line of text

Focus = the sector-capped top-20 selection (in_top) with rank 1..5. If the
sector cap skipped a raw rank 1-5, the focus has fewer than 5 stocks -- rank 6
is never promoted to fill it. Gold = review first, NOT a buy signal.
"""

import math
import os

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
RANKS = os.path.join(HERE, "data", "momentum_ranks_latest.csv")
TRACKER = os.path.join(HERE, "data", "signal_tracker_latest.csv")
TOP_N = 5
GOLD_FILL, GOLD_LIGHT, GOLD_TEXT = "F7E3A5", "FFF8E6", "79601E"
TOO_EARLY = 30
NOTE = ("Gold = momentum rank 1-5 (look here first). NOT a buy signal: per "
        "stock rank 1-5 beat the universe only ~50% of the time in 2013-26 "
        "(rank_study); the average comes from a few big winners.")


def _true(v):
    return str(v).strip().lower() in ("true", "1", "yes", "y")


def focus(ranks):
    """Rows (dicts) of the SELECTED stocks with numeric rank 1..TOP_N, best
    rank first, one per symbol. Accepts a ranks table with an in_top column
    (momentum_ranks_latest.csv) or the selected top table itself."""
    if ranks is None or len(ranks) == 0 or "symbol" not in ranks or \
            "rank" not in ranks:
        return []
    d = ranks.copy()
    d["symbol"] = d["symbol"].astype(str).str.upper().str.strip()
    d["rank"] = pd.to_numeric(d["rank"], errors="coerce")
    sel = d["in_top"].map(_true) if "in_top" in d else True
    d = d[sel & d["rank"].between(1, TOP_N) & (d["symbol"] != "") &
          (d["symbol"] != "NAN")]
    d = d.sort_values("rank").drop_duplicates("symbol")
    out = []
    for _, x in d.iterrows():
        r = x.to_dict()
        r["rank"] = int(r["rank"])
        out.append(r)
    return out


def load(path=RANKS):
    """(focus rows, ranks date or None, message). Never raises."""
    try:
        d = pd.read_csv(path)
    except Exception:
        return [], None, "momentum ranks not available (run rb first)"
    day = str(d["date"].iloc[0]) if "date" in d and len(d) else None
    rows = focus(d)
    if not rows:
        return [], day, "no selected stock with rank 1-%d in the ranks file" \
            % TOP_N
    return rows, day, ""


def symbols(rows):
    return {r["symbol"] for r in rows}


def cohort(t):
    """Momentum finds with Rank then 1-5 (rank WHEN FOUND, not today's):
    signals, unique stocks, avg / median return, beat Nifty (only finds with
    a Nifty comparison), tracking days, 30+ day count. None if no data."""
    if t is None or len(t) == 0 or "Source" not in t:
        return None
    rk = pd.to_numeric(t.get("Rank then"), errors="coerce")
    g = t[(t["Source"].astype(str) == "MOMENTUM") & rk.between(1, TOP_N)]
    ret = pd.to_numeric(g.get("Return %"), errors="coerce")
    g = g[ret.notna()]
    if not len(g):
        return None
    ret = pd.to_numeric(g["Return %"], errors="coerce")
    vs = pd.to_numeric(g.get("vs Nifty %"), errors="coerce").dropna()
    days = pd.to_numeric(g.get("Days since found"), errors="coerce").dropna()
    return {"signals": len(g), "stocks": g["Symbol"].nunique(),
            "avg": float(ret.mean()), "median": float(ret.median()),
            "best": float(ret.max()), "worst": float(ret.min()),
            "beat": int((vs > 0).sum()), "compared": len(vs),
            "days_min": int(days.min()) if len(days) else None,
            "days_max": int(days.max()) if len(days) else None,
            "old": int((days >= TOO_EARLY).sum())}


def load_cohort(path=TRACKER):
    try:
        return cohort(pd.read_csv(path))
    except Exception:
        return None


def cohort_line(c):
    if not c:
        return "no momentum rank 1-5 finds tracked yet"
    f = lambda v: "%+.1f%%" % v if v is not None and not (
        isinstance(v, float) and math.isnan(v)) else "n/a"
    days = "-" if c["days_min"] is None else (
        "%d" % c["days_min"] if c["days_min"] == c["days_max"]
        else "%d-%d" % (c["days_min"], c["days_max"]))
    early = " -> TOO EARLY to judge" if c["old"] < c["signals"] else ""
    return ("%d signals (%d stocks) | avg %s | median %s | best now %s | "
            "worst now %s | beat Nifty %d of %d | tracked %s days | 30+ days: "
            "%d of %d%s" % (c["signals"], c["stocks"], f(c["avg"]),
                            f(c["median"]), f(c["best"]), f(c["worst"]),
                            c["beat"], c["compared"], days, c["old"],
                            c["signals"], early))
