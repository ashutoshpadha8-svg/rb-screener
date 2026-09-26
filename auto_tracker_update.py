#!/usr/bin/env python3
"""
AUTO TRACKER UPDATE  --  Excel "BUY" rows -> split.csv (position_tracker.py)
=========================================================================

Run it ONLY after you have typed BUY in the "Action" column of the
Strategy_Comparison sheet and saved the file.

  1. Reads Strategy_Comparison from today's reports/RB_Screener_YYYY-MM-DD.xlsx
     (or --file PATH). Rows whose Action is "BUY" (any case) are taken.
  2. entry_price = today's live/closing price from Dhan (LTP). If Dhan is not
     available it uses the last close from the free source and says so.
  3. Shares = floor(slot / price), slot = Rs 2 lakh / 20 (momentum_screener
     settings). Cash market only -- exact integer shares, no F&O.
  4. Appends to split.csv:
       Momentum only / Super-Buy -> momentum_qty, strategy = Momentum
       W+TT only                 -> swing_qty,    strategy = W+TT
     with entry_date = today (YYYY-MM-DD) and entry_price.
  5. Duplicates are refused: a symbol that already has shares in split.csv
     (any leg) is skipped, so running this twice adds nothing twice.
     A copy of the previous file is kept as split_backup.csv.

RUN
    python3 ~/Desktop/RB_Screener/auto_tracker_update.py
    python3 ~/Desktop/RB_Screener/auto_tracker_update.py --dry-run   (show only)
"""

import warnings
warnings.filterwarnings("ignore")

import os
import sys
import shutil

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import daily_screener as ds
import momentum_screener as ms

SPLIT_FILE = ms.SPLIT_FILE
BACKUP = os.path.join(ds.HERE, "split_backup.csv")
COLUMNS = ["symbol", "swing_qty", "investing_qty", "momentum_qty",
           "entry_price", "entry_date", "strategy", "note"]


def read_split():
    """split.csv with the v3 columns (older files are upgraded in place)."""
    if not os.path.exists(SPLIT_FILE):
        return pd.DataFrame(columns=COLUMNS)
    sp = pd.read_csv(SPLIT_FILE)
    for c in COLUMNS:
        if c not in sp:
            sp[c] = 0 if c.endswith("_qty") else ""
    sp["symbol"] = sp["symbol"].astype(str).str.upper().str.strip()
    return sp[COLUMNS + [c for c in sp.columns if c not in COLUMNS]]


def already_held(sp):
    q = sum(pd.to_numeric(sp[c], errors="coerce").fillna(0)
            for c in ("swing_qty", "investing_qty", "momentum_qty"))
    return set(sp.loc[q > 0, "symbol"])


def buy_rows(path):
    try:
        d = pd.read_excel(path, sheet_name="Strategy_Comparison")
    except Exception as e:
        print("! Could not read Strategy_Comparison from %s (%s)."
              % (os.path.basename(path), e))
        print("  Run rbscan first (momentum_screener.py creates that sheet).")
        sys.exit(1)
    if "Ticker" not in d or "Action" not in d:
        print("! Strategy_Comparison has no Ticker/Action column.")
        sys.exit(1)
    act = d["Action"].astype(str).str.strip().str.upper()
    return d[act == "BUY"].copy()


def prices(tok, symbols):
    """{symbol: (price, source)} -- Dhan LTP first, free-source close second."""
    out = {}
    if tok:
        try:
            scrip = ds.load_scrip_map()
            ids = {s: scrip[s] for s in symbols if s in scrip}
            ltp = ds.dhan_ltp(tok, list(ids.values()))
            for s, i in ids.items():
                if i in ltp:
                    out[s] = (ltp[i], "Dhan")
        except Exception as e:
            print("! Dhan price fetch failed (%s) -- using last close." % e)
    for s in symbols:
        if s not in out:
            df = ds.fetch_eod(s.lower())
            if df is not None and len(df):
                out[s] = (float(df["Close"].iloc[-1]),
                          "close %s (free source, may be old)"
                          % df.index[-1].date())
    return out


def main():
    a = sys.argv[1:]
    dry = "--dry-run" in a
    path = a[a.index("--file") + 1] if "--file" in a else ms.todays_report()
    if not path or not os.path.exists(path):
        print("! No RB_Screener report found. Run rbscan first.")
        sys.exit(1)
    today = ds.now_ist().date().isoformat()
    if today not in os.path.basename(path):
        print("! Using %s -- it is NOT today's report (%s)."
              % (os.path.basename(path), today))

    rows = buy_rows(path)
    if rows.empty:
        print("No rows with Action = BUY in Strategy_Comparison of %s."
              % os.path.basename(path))
        print("Type BUY in the Action column, SAVE the file, then run again.")
        return
    sp = read_split()
    held = already_held(sp)
    todo, skipped = [], []
    for _, r in rows.iterrows():
        s = str(r["Ticker"]).upper().strip()
        if s in held or s in [t["symbol"] for t in todo]:
            skipped.append(s)
            continue
        todo.append({"symbol": s, "overlap": str(r.get("Strategy Overlap", ""))})
    if skipped:
        print("Already in split.csv (skipped, no duplicates): " +
              ", ".join(skipped))
    if not todo:
        print("Nothing new to add.")
        return

    tok = ms.get_token()
    px = prices(tok, [t["symbol"] for t in todo])
    new = []
    for t in todo:
        s = t["symbol"]
        if s not in px:
            print("! %s: no price available -- not added." % s)
            continue
        price, src = px[s]
        mom = t["overlap"] in ("Momentum only", "Super-Buy")
        shares = ms.shares_for(ms.CAPITAL / ms.SLOTS, price)
        if shares < 1:
            print("! %s: price %.1f > slot Rs %d -- 0 shares, not added."
                  % (s, price, ms.CAPITAL / ms.SLOTS))
            continue
        new.append({"symbol": s,
                    "swing_qty": 0 if mom else shares,
                    "investing_qty": 0,
                    "momentum_qty": shares if mom else 0,
                    "entry_price": round(price, 2), "entry_date": today,
                    "strategy": "Momentum" if mom else "W+TT",
                    "note": "%s | %s | %s" % (t["overlap"], src,
                                              os.path.basename(path))})
    if not new:
        return
    show = pd.DataFrame(new)
    print("\nTo add to %s:" % SPLIT_FILE)
    print(show[["symbol", "strategy", "momentum_qty", "swing_qty",
                "entry_price", "entry_date"]].to_string(index=False))
    print("  total: Rs %s" % format(int(sum(
        (n["momentum_qty"] + n["swing_qty"]) * n["entry_price"] for n in new)),
        ","))
    if dry:
        print("\n(--dry-run: nothing written)")
        return
    if os.path.exists(SPLIT_FILE):
        shutil.copyfile(SPLIT_FILE, BACKUP)
    out = pd.concat([sp, show[COLUMNS]], ignore_index=True)
    tmp = SPLIT_FILE + ".tmp"
    out.to_csv(tmp, index=False)
    os.replace(tmp, SPLIT_FILE)
    print("\nSaved %d new position(s) to split.csv (previous copy: "
          "split_backup.csv)." % len(new))
    print("Check them any day with: python3 ~/Desktop/RB_Screener/"
          "position_tracker.py")
    if any("free source" in n["note"] for n in new):
        print("! Some entry prices came from the free source, not Dhan -- "
              "edit entry_price in split.csv to your real fill price.")


if __name__ == "__main__":
    main()
