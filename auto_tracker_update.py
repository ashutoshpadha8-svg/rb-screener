#!/usr/bin/env python3
"""
AUTO TRACKER UPDATE + BROKER AMO BRIDGE  (rbtrack)
==================================================

Reads the "Action" column of the Actions sheet in today's
accounts/<BROKER>_<ID>/reports/Portfolio_<...>_YYYY-MM-DD.xlsx (made by
rbport; save + close Excel first):

  PAPER     -> added to split.csv with mode=PAPER (mock portfolio, no order,
               no effect on live money). Entry price = today's broker LTP/close.
  PAPER MTF -> same, but with the MTF (4x) quantity -- test leverage for free.
  BUY MTF   -> LIVE Margin Trading Facility order: productType MTF,
               quantity = floor(Rs 10,000 x 4 / price). Your own money stays
               ~Rs 10,000 per slot, the broker funds the rest at 12.49%/yr.
               BACKTEST (momentum top 20, 2013-26): 1x 22.8%/yr, max DD -35%;
               4x 18.4%/yr, max DD -97.5%, worst month -73% -> in real life a
               margin call would have closed you out at the Mar-2020 bottom.
               You must type "YES MTF" to send MTF orders.
  BUY       -> LIVE. By default places an AMO (After Market Order) with the
             ACTIVE account's broker (broker_api.py: Dhan CNC / Angel DELIVERY /
             Kite CNC), NSE, BUY, MARKET at the next open
             = the backtest's "buy next open". Shares = floor(Rs slot / price).
           You see every order and must type YES before anything is sent.
           Only orders the broker ACCEPTS are written to split.csv (mode=LIVE,
           order_id kept, entry_price provisional until --sync).

OPTIONS
  --dry-run     show what would happen, send nothing, write nothing
  --no-orders   BUY rows go to split.csv as LIVE without placing orders
                (you buy manually in the broker app)
  --limit       LIMIT AMO at last price + LIMIT_BUFFER instead of MARKET
  --sync        after the market opens: read fills from the broker and set the real
                entry_price / quantity for LIVE rows whose order is pending;
                rejected / cancelled orders are marked and set to 0 shares
  --file PATH   use another report
  --unwatch A,B remove symbols from the watchlist

  WATCH       -> no order; the symbol goes on this account's watchlist
                 (data/watchlist.csv) and rbport analyses it every run

SAFETY
  * AMOs are refused during market hours (09:15-15:30) -- run it at night.
  * The token must belong to the active Client ID (Dhan: signed in the token;
    Angel/Zerodha: asked from the broker) or nothing is sent.
  * Funds are checked before any order; not enough -> nothing.
  * A symbol already held (same mode) in split.csv, or already ordered today
    (data/orders_log.csv), is skipped -> running twice never double-buys.
  * split.csv is backed up to split_backup.csv before every write.
  * First time: test with ONE row / ONE share.
"""

import warnings
warnings.filterwarnings("ignore")

import os
import sys
import shutil
import datetime as dt

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import daily_screener as ds
import momentum_screener as ms
import broker_api as ba
import portfolio as pf

SPLIT_FILE = ms.SPLIT_FILE
BACKUP = os.path.join(ds.HERE, "split_backup.csv")
WATCH_FILE = os.path.join(ds.DATA, "watchlist.csv")     # routed per account
COLUMNS = ["symbol", "swing_qty", "investing_qty", "momentum_qty",
           "entry_price", "entry_date", "strategy", "mode", "product",
           "order_id", "note"]
QTY = ("swing_qty", "investing_qty", "momentum_qty")
LIMIT_BUFFER = 0.02        # --limit: pay at most 2% above the last price
MTF_LEVERAGE = 4           # BUY MTF: quantity = floor(slot x 4 / price)
ACTIONS = {"BUY": ("LIVE", "CNC"), "BUY MTF": ("LIVE", "MTF"),
           "PAPER": ("PAPER", "CNC"), "PAPER MTF": ("PAPER", "MTF")}


# ================================================================== split.csv
def read_split():
    """split.csv with the v4 columns (older files are upgraded)."""
    if not os.path.exists(SPLIT_FILE):
        return pd.DataFrame(columns=COLUMNS)
    sp = pd.read_csv(SPLIT_FILE, dtype={"order_id": str})
    for c in COLUMNS:
        if c not in sp:
            sp[c] = 0 if c.endswith("_qty") else ""
    sp["mode"] = sp["mode"].fillna("").replace("", "LIVE").astype(str).str.upper()
    sp["product"] = sp["product"].fillna("").replace("", "CNC").astype(str).str.upper()
    sp["symbol"] = sp["symbol"].astype(str).str.upper().str.strip()
    for c in QTY:
        sp[c] = pd.to_numeric(sp[c], errors="coerce").fillna(0)
    return sp[COLUMNS + [c for c in sp.columns if c not in COLUMNS]]


def write_split(sp):
    if os.path.exists(SPLIT_FILE):
        shutil.copyfile(SPLIT_FILE, BACKUP)
    tmp = SPLIT_FILE + ".tmp"
    sp.to_csv(tmp, index=False)
    os.replace(tmp, SPLIT_FILE)


def held(sp, mode):
    q = sum(sp[c] for c in QTY)
    return set(sp.loc[(q > 0) & (sp["mode"] == mode), "symbol"])


# ================================================================== excel
def action_rows(path):
    try:
        d = pd.read_excel(path, sheet_name="Actions")
    except Exception as e:
        print("! Could not read the Actions sheet from %s (%s)."
              % (os.path.basename(path), e))
        print("  Run rbport first (it makes Portfolio_..xlsx with Actions).")
        sys.exit(1)
    if "Ticker" not in d or "Action" not in d:
        print("! Actions sheet has no Ticker/Action column.")
        sys.exit(1)
    # "buy  mtf" / "Buy MTF" -> "BUY MTF"; anything else is ignored
    d["act"] = d["Action"].astype(str).str.upper().str.split().str.join(" ")
    bad = d[(d["Action"].notna()) & (d["act"] != "NAN") & (d["act"] != "")
            & (d["act"] != "WATCH") & ~d["act"].isin(list(ACTIONS))]
    if len(bad):
        print("! Ignored unknown Action values: " + ", ".join(
            "%s='%s'" % (t, a) for t, a in zip(bad["Ticker"], bad["Action"])))
    return d[d["act"].isin(list(ACTIONS) + ["WATCH"])].copy()


def load_watch():
    cols = ["symbol", "added", "price_added", "source"]
    if not os.path.exists(WATCH_FILE):
        return pd.DataFrame(columns=cols)
    return pd.read_csv(WATCH_FILE)


def save_watch(rows):
    """WATCH picks -> accounts/<..>/data/watchlist.csv (no order, no money).
    rbport then analyses them next to your holdings."""
    w = load_watch()
    have = set(w["symbol"].astype(str).str.upper())
    add = []
    for _, r in rows.iterrows():
        s = str(r["Ticker"]).upper().strip()
        if s in have:
            continue
        add.append({"symbol": s, "added": ds.now_ist().date().isoformat(),
                    "price_added": r.get("LTP"),
                    "source": r.get("Strategy Overlap", "")})
        have.add(s)
    if add:
        pd.concat([w, pd.DataFrame(add)], ignore_index=True).to_csv(
            WATCH_FILE, index=False)
    return [x["symbol"] for x in add]


def unwatch(symbols):
    w = load_watch()
    keep = w[~w["symbol"].astype(str).str.upper().isin(symbols)]
    keep.to_csv(WATCH_FILE, index=False)
    return len(w) - len(keep)


# ================================================================== prices
def prices(sess, symbols):
    """{symbol: (price, source)} -- broker LTP first, free-source close second."""
    out = {}
    if sess:
        try:
            ltp = ba.live_prices(sess, symbols)
            for s, p in ltp.items():
                out[s] = (p, sess.label)
        except Exception as e:
            print("! %s price fetch failed (%s) -- using last close."
                  % (sess.label, e))
    for s in symbols:
        if s not in out:
            df = ds.fetch_eod(s.lower())
            if df is not None and len(df):
                out[s] = (float(df["Close"].iloc[-1]),
                          "close %s (free source, may be old)"
                          % df.index[-1].date())
    return out


def plan(rows, px, sp):
    """Turn Excel rows into split.csv rows (not written yet)."""
    new, skip = [], []
    today = ds.now_ist().date().isoformat()
    for _, r in rows.iterrows():
        s = str(r["Ticker"]).upper().strip()
        mode, product = ACTIONS[r["act"]]
        if s in held(sp, mode) or any(x["symbol"] == s and x["mode"] == mode
                                      for x in new):
            skip.append("%s (%s already in split.csv)" % (s, mode))
            continue
        if mode == "LIVE" and ba.ordered_today(s):
            skip.append("%s (order already placed today)" % s)
            continue
        if s not in px:
            skip.append("%s (no price)" % s)
            continue
        price, src = px[s]
        overlap = str(r.get("Strategy Overlap", ""))
        mom = overlap in ("Momentum only", "Super-Buy")
        slot = ms.CAPITAL / ms.SLOTS              # your own money per slot
        exposure = slot * (MTF_LEVERAGE if product == "MTF" else 1)
        shares = ms.shares_for(exposure, price)
        if shares < 1:
            skip.append("%s (price %.0f > Rs %d)" % (s, price, exposure))
            continue
        new.append({"symbol": s, "swing_qty": 0 if mom else shares,
                    "investing_qty": 0, "momentum_qty": shares if mom else 0,
                    "entry_price": round(price, 2), "entry_date": today,
                    "strategy": "Momentum" if mom else "W+TT", "mode": mode,
                    "product": product, "order_id": "", "shares": shares,
                    "note": "%s | %s%s" % (overlap, src,
                                           " | MTF %dx" % MTF_LEVERAGE
                                           if product == "MTF" else "")})
    return new, skip


# ================================================================== orders
def place_orders(sess, live, use_limit, dry):
    """Returns the rows whose AMO the broker accepted (order_id filled in)."""
    if not live:
        return []
    if ds.market_open():
        print("\n! Market is open (09:15-15:30). AMOs are placed after hours "
              "-- run rbtrack tonight, or use --no-orders.")
        return []
    known = ba.symbol_map(sess)
    missing = [x["symbol"] for x in live if x["symbol"] not in known]
    if missing:
        print("! Not in the %s symbol list, skipped: %s"
              % (sess.label, ", ".join(missing)))
    live = [x for x in live if x["symbol"] in known]
    if not live:
        return []
    total = sum(x["shares"] * x["entry_price"] for x in live)
    own = sum(x["shares"] * x["entry_price"] /
              (MTF_LEVERAGE if x["product"] == "MTF" else 1) for x in live)
    mtf = [x for x in live if x["product"] == "MTF"]
    otype = "LIMIT" if use_limit else "MARKET"
    print("\n%s AMO ORDERS -- account %s (BUY, %s at next open):"
          % (sess.label.upper(), sess.client_id, otype))
    for x in live:
        lim = round(x["entry_price"] * (1 + LIMIT_BUFFER), 1)
        print("  %-12s %-3s qty %4d  exposure ~Rs %9s%s" % (
            x["symbol"], x["product"], x["shares"],
            format(int(x["shares"] * x["entry_price"]), ","),
            "  limit %.1f" % lim if use_limit else ""))
    print("  total exposure ~Rs %s | your own money ~Rs %s "
          "(MARKET fills at the open, can differ)"
          % (format(int(total), ","), format(int(own), ",")))
    if mtf:
        funded = sum(x["shares"] * x["entry_price"] * (1 - 1.0 / MTF_LEVERAGE)
                     for x in mtf)
        print("\n  !!! MTF: broker-funded ~Rs %s at 12.49%%/yr = ~Rs %d per "
              "day interest." % (format(int(funded), ","), funded * 0.1249 / 365))
        print("  !!! At %dx a %d%% fall wipes out the money you put in. "
              "Backtest: 4x momentum max DD -97.5%% (1x: -35%%)."
              % (MTF_LEVERAGE, 100 // MTF_LEVERAGE))
        print("  !!! Not every stock gets 4x on %s -- if the stock's MTF "
              "limit is lower, the broker will reject or ask more margin."
              % sess.label)
        if sess.broker != "DHAN":
            print("  !!! 12.49%% is Dhan's MTF rate; %s charges its own."
                  % sess.label)
    if dry:
        print("(--dry-run: no orders sent)")
        return []
    ok, msg = ba.verify_identity(sess)
    if not ok:
        print("! Account check failed: %s. No orders sent." % msg)
        return []
    print("  %s" % msg)
    funds, err = ba.available_funds(sess)
    if funds is None:
        print("! Could not read %s funds (%s). No orders sent."
              % (sess.label, err))
        return []
    print("  %s available balance: Rs %s" % (sess.label,
                                            format(int(funds), ",")))
    if funds < own * 1.02:
        print("! Not enough funds for all orders (need ~Rs %s of your own "
              "money incl. buffer). No orders sent." % format(int(own * 1.02),
                                                               ","))
        return []
    word = "YES MTF" if mtf else "YES"
    ans = input("\nType %s to send these %d order(s) to %s account %s: "
                % (word, len(live), sess.label, sess.client_id))
    if " ".join(ans.upper().split()) != word:
        print("Cancelled -- nothing sent.")
        return []
    accepted = []
    for x in live:
        lim = round(round(x["entry_price"] * (1 + LIMIT_BUFFER) / 0.05) * 0.05, 2)
        ok, res, status = ba.place_amo_order(
            x["symbol"], x["shares"], x["product"] == "MTF", sess=sess,
            order_type=otype, price=lim if use_limit else 0.0)
        ba.log_order({"date": dt.date.today().isoformat(),
                      "broker": sess.broker, "client_id": sess.client_id,
                      "time": ds.now_ist().strftime("%H:%M:%S"),
                      "symbol": x["symbol"], "qty": x["shares"],
                      "product": x["product"],
                      "type": otype, "ok": ok, "order_id": res if ok else "",
                      "status": status, "error": "" if ok else res})
        if ok:
            print("  OK   %-12s %s order %s (%s)" % (x["symbol"], x["product"],
                                                   res, status))
            x["order_id"] = res
            x["note"] += " | AMO %s pending -> rbtrack --sync" % otype
            accepted.append(x)
        else:
            print("  FAIL %-12s %s" % (x["symbol"], res))
            if "token" in res or "HTTP 401" in res or "HTTP 403" in res or \
                    "identity" in res:
                print("! Stopping: authentication problem.")
                break
    return accepted


def sync(sess):
    """Replace provisional entry prices with real fills."""
    sp = read_split()
    pend = sp[(sp["mode"] == "LIVE") & (sp["order_id"].astype(str).str.len() > 3)
              & sp["note"].astype(str).str.contains("pending")]
    if pend.empty:
        print("No pending AMO rows in split.csv.")
        return
    for i, r in pend.iterrows():
        oid = str(r["order_id"]).split(".")[0]
        o = ba.check_order_status(oid, sess=sess)
        q, avg, st = o["filled_qty"], o["avg_price"], o["status"] or o["raw"] or "?"
        leg = "momentum_qty" if r["momentum_qty"] > 0 else "swing_qty"
        if q > 0 and avg:
            sp.at[i, leg] = q
            sp.at[i, "entry_price"] = round(avg, 2)
            sp.at[i, "note"] = str(r["note"]).replace("pending", "filled")
            print("  %-12s filled %d @ %.2f" % (r["symbol"], q, avg))
        elif st in ("REJECTED", "CANCELLED", "EXPIRED"):
            sp.at[i, leg] = 0
            sp.at[i, "note"] = str(r["note"]).replace("pending", st.lower())
            print("  %-12s %s -- set to 0 shares" % (r["symbol"], st))
        else:
            print("  %-12s still %s" % (r["symbol"], st))
    write_split(sp)


# ================================================================== main
def main():
    import account
    acc = account.activate()
    a = sys.argv[1:]
    dry, no_orders, use_limit = ("--dry-run" in a, "--no-orders" in a,
                                 "--limit" in a)
    if "--unwatch" in a and a.index("--unwatch") + 1 < len(a):
        syms = [x.strip().upper() for x in
                a[a.index("--unwatch") + 1].split(",") if x.strip()]
        print("Removed %d from the watchlist." % unwatch(syms))
        return
    sess = ms.get_session()
    if "--sync" in a:
        if not sess:
            print("! --sync needs a valid (not expired) broker token.")
            sys.exit(1)
        sync(sess)
        account.banner(acc)
        return
    path = a[a.index("--file") + 1] if "--file" in a else pf.latest()
    if not path or not os.path.exists(path):
        print("! No Portfolio file found. Run rbscan, then rbport.")
        sys.exit(1)
    today = ds.now_ist().date().isoformat()
    if today not in os.path.basename(path):
        print("! Using %s -- NOT today's report (%s)." % (os.path.basename(path),
                                                         today))
    rows = action_rows(path)
    watch = rows[rows["act"] == "WATCH"]
    rows = rows[rows["act"] != "WATCH"]
    if len(watch):
        added = save_watch(watch) if not dry else []
        print("WATCH (no order, no money): %s -> %s" % (
            ", ".join(watch["Ticker"].astype(str)),
            "added to your watchlist; rbport analyses them"
            if added else ("already on the watchlist" if not dry
                           else "(--dry-run: not saved)")))
        print("  remove later with:  rbtrack --unwatch SYMBOL")
    if rows.empty and len(watch):
        account.banner(acc)
        return
    if rows.empty:
        print("No BUY / BUY MTF / PAPER / PAPER MTF in the Action column of "
              "the Actions sheet (%s)." % os.path.basename(path))
        print("Type one of them, SAVE and CLOSE the file, then run again.")
        return
    sp = read_split()
    px = prices(sess, [str(t).upper().strip() for t in rows["Ticker"]])
    new, skip = plan(rows, px, sp)
    if skip:
        print("Skipped: " + "; ".join(skip))
    if not new:
        print("Nothing new to add.")
        return
    paper = [x for x in new if x["mode"] == "PAPER"]
    live = [x for x in new if x["mode"] == "LIVE"]

    if live and not no_orders:
        if not sess:
            print("! BUY rows need a valid broker token to place AMOs "
                  "(or use --no-orders). LIVE rows not added.")
            live = []
        else:
            live = place_orders(sess, live, use_limit, dry)
    add = paper + live
    if not add:
        return
    show = pd.DataFrame(add)
    print("\nTo add to split.csv:")
    print(show[["symbol", "mode", "product", "strategy", "momentum_qty",
                "swing_qty", "entry_price", "order_id"]].to_string(index=False))
    if dry:
        print("\n(--dry-run: nothing written)")
        return
    write_split(pd.concat([sp, show[COLUMNS]], ignore_index=True))
    print("\nSaved %d row(s) (previous copy: split_backup.csv)." % len(add))
    if any("free source" in x["note"] for x in add):
        print("! Some prices came from the free source, not the broker.")
    if live:
        print("After tomorrow's open run:  rbtrack --sync   (real fill prices)")
    account.banner(acc)


if __name__ == "__main__":
    main()
