#!/usr/bin/env python3
"""
AUTO TRACKER UPDATE + BROKER AMO BRIDGE  (rbtrack)
==================================================

Reads the Buy_Planner sheet (Pick BUY / MTF / WATCH + Qty; 6 Oct 2026 -- old
files: the "Action" column of the Actions sheet) in today's
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
                entry_price / quantity; recover missing BUY rows by intent tag;
                cancelled partial fills keep their actual shares; a missing
                final average price remains pending for later reconciliation
  --file PATH   use another report
  --unwatch A,B remove symbols from the watchlist
  --clear-paper remove all PAPER rows (PAPER mode is gone since 27 Sep)
  --sold SYM [PRICE] [--date YYYY-MM-DD] [--paper]
                close a trade in the journal by hand (LIVE sell the broker
                history did not show, or a PAPER sell; PAPER without PRICE =
                last price). Also takes it out of split.csv.

  WATCH       -> no order; the symbol goes on this account's watchlist
                 (data/watchlist.csv) and rbport analyses it every run

SAFETY
  * AMOs are refused during market hours (09:15-15:30) -- run it at night.
  * The token must belong to the active Client ID (Dhan: signed in the token;
    Angel/Zerodha: asked from the broker) or nothing is sent.
  * Funds are checked before any order; not enough -> nothing.
  * A symbol already held (same mode), or with an unresolved/pending BUY intent,
    is skipped. Missing BUY positions are recovered before planning new orders.
  * split.csv is backed up to split_backup.csv before every write.
  * First time: test with ONE row / ONE share.
"""

import warnings
warnings.filterwarnings("ignore")

import os
import sys
import shutil
import json
import datetime as dt

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import daily_screener as ds
import momentum_screener as ms
import broker_api as ba
import portfolio as pf
from position_sizing import slot_budget

SPLIT_FILE = ms.SPLIT_FILE
BACKUP = os.path.join(ds.HERE, "split_backup.csv")
WATCH_FILE = os.path.join(ds.DATA, "watchlist.csv")     # routed per account
COLUMNS = ["symbol", "swing_qty", "investing_qty", "momentum_qty",
           "entry_price", "entry_date", "strategy", "mode", "product",
           "order_id", "note"]
QTY = ("swing_qty", "investing_qty", "momentum_qty")
TRACKING_COLS = ["intent_tag", "ordered_qty", "filled_qty_confirmed",
                 "fill_avg_price", "fill_avg_qty", "price_pending"]
LIMIT_BUFFER = 0.02        # --limit: pay at most 2% above the last price
MTF_LEVERAGE = 4           # BUY MTF fallback when the broker gives no leverage;
                           # Dhan: real per-stock leverage (margin calculator)
ACTIONS = {"BUY": ("LIVE", "CNC"), "BUY MTF": ("LIVE", "MTF")}   # PAPER removed
                                                             # 27 Sep (RB)


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
    with open(tmp, "w", newline="") as f:
        sp.to_csv(f, index=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, SPLIT_FILE)


def held(sp, mode):
    q = sum(sp[c] for c in QTY)
    return set(sp.loc[(q > 0) & (sp["mode"] == mode), "symbol"])


# ================================================================== excel
def action_rows(path):
    """Old Portfolio files' Actions sheet (6 Oct 2026: everything moved to
    Buy_Planner) -- missing sheet = no rows, not an error."""
    empty = pd.DataFrame(columns=["Ticker", "Action", "act",
                                  "Strategy Overlap", "Amount (Rs)"])
    if not os.path.exists(path):
        print("! %s not found -- run rb first." % path)
        sys.exit(1)
    try:
        d = pd.read_excel(path, sheet_name="Actions")
    except Exception:
        return empty
    if "Ticker" not in d or "Action" not in d:
        return empty
    # "buy  mtf" / "Buy MTF" -> "BUY MTF"; anything else is ignored
    d["act"] = d["Action"].fillna("").astype(str).str.upper().str.split() \
        .str.join(" ")
    bad = d[(d["Action"].notna()) & (d["act"] != "NAN") & (d["act"] != "")
            & (d["act"] != "WATCH") & ~d["act"].isin(list(ACTIONS))]
    if len(bad):
        print("! Ignored unknown Action values: " + ", ".join(
            "%s='%s'" % (t, a) for t, a in zip(bad["Ticker"], bad["Action"])))
    return d[d["act"].isin(list(ACTIONS) + ["WATCH"])].copy()


def planner_rows(path):
    """Buy_Planner BUY / MTF / WATCH rows -> the old Actions row shape, with
    the FINAL QTY recomputed by buy_planner.distribute() from the sheet's own
    inputs (never the cached formula values)."""
    import buy_planner as bp
    inp, prow = bp.read_sheet(path)
    if not prow or not any(r["pick"] for r in prow):
        return pd.DataFrame(), None
    out, summ = bp.distribute(prow, inp.get("budget"), inp.get("shares"),
                              inp.get("mtf_lev"))
    rows = []
    for r in out:
        why = str(r.get("why", ""))
        ov = "Super-Buy" if why.startswith("Super-Buy") else \
            "Momentum only" if why.startswith("Momentum") else "W+TT only"
        if r["pick"] == "WATCH":
            rows.append({"Ticker": r["symbol"], "Action": "WATCH",
                         "act": "WATCH", "Strategy Overlap": ov,
                         "LTP": r["price"], "Amount (Rs)": "", "Qty": None})
            continue
        if r["final"] < 1:
            continue
        mtf = r["pick"] == "MTF"
        rows.append({"Ticker": r["symbol"], "Action": "BUY MTF" if mtf
                     else "BUY", "act": "BUY MTF" if mtf else "BUY",
                     "Strategy Overlap": ov,
                     # auto MTF: own money fixed, broker leverage sets qty;
                     # your own Qty (or a normal BUY) = exactly that qty
                     "Amount (Rs)": round(r["amount"], 2)
                     if mtf and r["qty_you"] is None else "",
                     "Qty": None if mtf and r["qty_you"] is None
                     else int(r["final"]), "Planner price": r["price"]})
    print("Buy_Planner: budget Rs %s | Mid / Large / Small %s | planned Rs %s "
          "| bacha Rs %s" % (
              format(int(summ["budget"]), ","),
              " / ".join("%d%%" % round(100 * summ["eff"][c])
                         for c in bp.ORDER),
              format(int(summ["total"]), ","), format(int(summ["left"]), ",")))
    for x in rows:
        print("  %-12s %-7s %s  (%s)" % (
            x["Ticker"], x["act"], "%d sh" % x["Qty"] if x["Qty"] else
            ("own Rs %s, broker leverage" % format(int(x["Amount (Rs)"]), ",")
             if x["act"] == "BUY MTF" else "no order"),
            x["Strategy Overlap"]))
    return pd.DataFrame(rows), summ


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


def today_str():
    return ds.now_ist().date().isoformat()


def _sectors():
    try:
        r = pd.read_csv(ms.RANKS_FILE)
        return dict(zip(r["symbol"].astype(str).str.upper(),
                        r["sector"].fillna("?").astype(str)))
    except Exception:
        return {}


def _mom_book(sp, mode, sess):
    """Momentum holdings of one mode that take a slot: every split.csv
    Momentum row. A SELL that is only SENT still holds its slot (it may be
    rejected) -- the slot frees once the sale is confirmed and the row
    leaves split.csv. Untracked BUY intents also reserve a slot until
    reconciled. Cost: rebalance buys go one session after the sells --
    buy_delay_study.py: 20.9 -> 20.4% post-tax (~0.5 pt/yr), the price of
    never holding 21."""
    m = (sp["strategy"].astype(str).str.lower() == "momentum") & \
        (sp["momentum_qty"] > 0) & (sp["mode"] == mode)
    reserved = ba.buy_reservations(sp) if mode == "LIVE" else []
    return list(dict.fromkeys(list(sp.loc[m, "symbol"]) + reserved))


def plan(rows, px, sp, sess=None, slot=None):
    """Turn Excel rows into split.csv rows (not written yet). Momentum buys
    are refused past 20 positions or 4 per industry (holdings + this run),
    the backtest's limits (Codex review 30 Sep)."""
    new, skip = [], []
    today = ds.now_ist().date().isoformat()
    secmap = _sectors()
    book = {}
    for _, r in rows.iterrows():
        s = str(r["Ticker"]).upper().strip()
        mode, product = ACTIONS[r["act"]]
        if s in held(sp, mode) or any(x["symbol"] == s and x["mode"] == mode
                                      for x in new):
            skip.append("%s (%s already in split.csv)" % (s, mode))
            continue
        if mode == "LIVE" and ba.ordered_today(s, sess=sess):
            skip.append("%s (order already placed today)" % s)
            continue
        if s not in px:
            skip.append("%s (no price)" % s)
            continue
        price, src = px[s]
        overlap = str(r.get("Strategy Overlap", ""))
        mom = overlap in ("Momentum only", "Super-Buy")
        if mom:
            if mode not in book:
                book[mode] = _mom_book(sp, mode, sess)
            cur = book[mode]
            sec = secmap.get(s, "?")
            nsec = sum(1 for x in cur if secmap.get(x, "?") == sec)
            if len(cur) >= ms.SLOTS:
                skip.append("%s (momentum full: %d of %d slots used)"
                            % (s, len(cur), ms.SLOTS))
                continue
            if ms.SECTOR_CAP and sec != "?" and nsec >= ms.SECTOR_CAP:
                skip.append("%s (momentum: already %d in %s, cap %d)"
                            % (s, nsec, sec, ms.SECTOR_CAP))
                continue
        slot_rs = slot or slot_budget(ms.CAPITAL, ms.SLOTS)  # acct value/20
        amt = pd.to_numeric(str(r.get("Amount (Rs)", "")).replace(",", ""),
                            errors="coerce")        # Actions sheet, optional
        if amt == amt and amt > 0:
            slot_rs = float(amt)
        lev, lev_note = 1.0, ""
        if product == "MTF":
            lev, lev_note = ba.mtf_leverage(sess, s, price)
            if lev is None:
                lev, lev_note = float(MTF_LEVERAGE), \
                    "MTF %gx ASSUMED (%s)" % (MTF_LEVERAGE, lev_note)
        exposure = slot_rs * lev
        shares = ms.shares_for(exposure, price)
        pq = pd.to_numeric(r.get("Qty"), errors="coerce")
        if pq == pq and pq >= 1:                        # Buy_Planner qty
            shares = int(pq)
            slot_rs = shares * price / lev
            src = "Buy_Planner qty | " + src
        if shares < 1:
            skip.append("%s (price %.0f > Rs %d)" % (s, price, exposure))
            continue
        if mom:
            book[mode].append(s)
        new.append({"symbol": s, "swing_qty": 0 if mom else shares,
                    "investing_qty": 0, "momentum_qty": shares if mom else 0,
                    "entry_price": round(price, 2), "entry_date": today,
                    "strategy": "Momentum" if mom else "W+TT", "mode": mode,
                    "product": product, "order_id": "", "shares": shares,
                    "lev": lev,
                    "note": "%s | own Rs %s | %s%s" % (overlap,
                                                        format(int(slot_rs), ","),
                                                        src,
                                           " | " + lev_note
                                           if product == "MTF" else "")})
    return new, skip


# ================================================================== orders
_LOCK = None


def take_lock():
    """One rbtrack per account at a time: a second copy started while the
    first is sending orders stops here (no two processes, one order)."""
    global _LOCK
    import fcntl
    p = os.path.join(os.path.dirname(ba.ORDER_LOG), "rbtrack.lock")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    f = open(p, "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, OSError):
        f.close()
        return False
    _LOCK = f
    return True


def send_one(sess, sym, qty, product, side, otype="MARKET", price=0.0,
             position=None):
    """intent saved -> order sent with the intent's tag -> result saved.
    If saving the result fails after the broker accepted, the intent stays
    unresolved and the next run finds the order by its tag (never re-sent)."""
    tag = ba.new_intent(sym, side, qty, product, position=position)
    if position is not None:
        position["intent_tag"] = tag
        position["ordered_qty"] = qty
        position["filled_qty_confirmed"] = 0
        position["fill_avg_price"] = 0
        position["fill_avg_qty"] = 0
        position["price_pending"] = 1
    ok, res, status = ba.place_amo_order(sym, qty, product == "MTF",
                                         sess=sess, order_type=otype,
                                         price=price, side=side, tag=tag)
    try:
        ba.update_intent(tag, state="ACCEPTED" if ok else
                         ("UNKNOWN" if status == "UNKNOWN" else "REJECTED"),
                         order_id=res if ok else "", status=status,
                         note="" if ok else str(res)[:120])
        ba.log_order({"date": dt.date.today().isoformat(),
                      "broker": sess.broker, "client_id": sess.client_id,
                      "time": ds.now_ist().strftime("%H:%M:%S"),
                      "symbol": sym, "qty": qty, "side": side,
                      "product": product, "type": otype, "ok": ok,
                      "order_id": res if ok else "", "status": status,
                      "error": "" if ok else res})
    except Exception as e:
        print("  !!! %s %s: result NOT saved (%s). Intent %s stays open -> "
              "the next rbtrack checks the broker before anything else."
              % (side, sym, type(e).__name__, tag))
    if status == "UNKNOWN":
        print("  ?? %s %s: reply lost, not in the order book yet. Check the "
              "broker app, then: rbtrack --resolve %s placed|not-placed"
              % (side, sym, tag))
    return ok, res, status


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
              x.get("lev", 1) for x in live)
    mtf = [x for x in live if x["product"] == "MTF"]
    otype = "LIMIT" if use_limit else "MARKET"
    print("\n%s AMO ORDERS -- account %s (BUY, %s at next open):"
          % (sess.label.upper(), sess.client_id, otype))
    for x in live:
        lim = round(x["entry_price"] * (1 + LIMIT_BUFFER), 1)
        print("  %-12s %-3s qty %4d  exposure ~Rs %9s%s%s" % (
            x["symbol"], x["product"], x["shares"],
            format(int(x["shares"] * x["entry_price"]), ","),
            "  limit %.1f" % lim if use_limit else "",
            "  (%s)" % x["note"].split(" | ")[-1]
            if x["product"] == "MTF" else ""))
    print("  total exposure ~Rs %s | your own money ~Rs %s "
          "(MARKET fills at the open, can differ)"
          % (format(int(total), ","), format(int(own), ",")))
    if mtf:
        funded = sum(x["shares"] * x["entry_price"] * (1 - 1.0 / x["lev"])
                     for x in mtf)
        top = max(x["lev"] for x in mtf)
        print("\n  !!! MTF: broker-funded ~Rs %s at 12.49%%/yr = ~Rs %d per "
              "day interest." % (format(int(funded), ","), funded * 0.1249 / 365))
        print("  !!! At %.2fx a %.0f%% fall wipes out the money you put in. "
              "Backtest: 4x momentum max DD -97.5%% (1x: -35%%)."
              % (top, 100 / top))
        if any("ASSUMED" in x["note"] for x in mtf):
            print("  !!! Leverage ASSUMED %gx for some rows -- if the stock's "
                  "MTF limit on %s is lower, the broker will reject or ask "
                  "more margin." % (MTF_LEVERAGE, sess.label))
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
        ok, res, status = send_one(sess, x["symbol"], x["shares"],
                                   x["product"], "BUY", otype,
                                   lim if use_limit else 0.0, position=x)
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


def _number(value, default=0.0):
    try:
        n = float(value)
        return default if pd.isna(n) else n
    except (TypeError, ValueError):
        return default


def _fill_row(row, order):
    """Keep cumulative fills and price reconciliation separate from finality."""
    row = dict(row)
    leg = next((c for c in QTY if _number(row.get(c)) > 0),
               "momentum_qty" if row.get("strategy") == "Momentum" else
               "investing_qty" if row.get("strategy") == "SIP" else "swing_qty")
    last = int(_number(row.get("filled_qty_confirmed")))
    reported = int(order.get("filled_qty") or 0)
    q = max(last, reported)
    previous_avg = _number(row.get("fill_avg_price"))
    previous_avg_qty = int(_number(row.get("fill_avg_qty")))
    avg = order.get("avg_price")
    if reported < last or not avg:
        avg = previous_avg if previous_avg_qty == q and previous_avg > 0 else None
    st = order.get("status") or order.get("raw") or "?"
    final = st in ("TRADED", "REJECTED", "CANCELLED", "EXPIRED")
    ordered = int(_number(row.get("ordered_qty")) or _number(row.get(leg)))
    note = str(row.get("note") or "AMO pending")
    note = note.replace(" | fill price pending", "")
    row.update(ordered_qty=ordered, filled_qty_confirmed=q)
    if q > 0:
        row[leg] = q
        row["price_pending"] = int(not avg)
        if avg:
            row["entry_price"] = round(float(avg), 2)
            row["fill_avg_price"] = float(avg)
            row["fill_avg_qty"] = q
        if final:
            part = "" if q >= ordered else " (partial: %d of %d, rest %s)" % (
                q, ordered, str(st).lower())
            note = note.replace("pending", "filled" + part)
        elif "pending" not in note:
            note += " | order pending"
        if not avg:
            note += " | fill price pending"
    elif st in ("REJECTED", "CANCELLED", "EXPIRED"):
        row[leg] = 0
        row["price_pending"] = 0
        note = note.replace("pending", st.lower())
    row["note"] = note
    return row


def _mark_saved(rows):
    """Commit ledger markers only after the position file is durable."""
    ledger = ba.load_intents()
    for row in rows:
        oid = str(row.get("order_id") or "")
        if not oid or oid == "nan":
            continue               # manual rows cannot reconcile an unrelated intent
        found = ledger[(ledger["side"] == "BUY") & (ledger["order_id"] == oid)]
        for _, intent in found.iterrows():
            ba.update_intent(intent["tag"], position_saved="1",
                             filled_qty=max(int(_number(row.get("filled_qty_confirmed"))),
                                            int(_number(intent["filled_qty"]))),
                             avg_price=_number(row.get("fill_avg_price")) or intent["avg_price"],
                             avg_qty=int(_number(row.get("fill_avg_qty"))) or intent["avg_qty"])


def recover_buys(sess, sp=None):
    """Restore missing BUY rows by order ID using pre-POST position metadata.

    Called under rbtrack's account lock. A crash after the split write is
    harmless: the next recovery finds its order ID instead of appending it.
    Legacy rows without metadata remain reserved/blocked for manual review.
    """
    sp = read_split() if sp is None else sp.copy()
    recovered = []
    orders = set(sp["order_id"].fillna("").astype(str))
    for _, intent in ba.load_intents().iterrows():
        if intent["side"] != "BUY" or intent["state"] in ("REJECTED", "NOT_PLACED"):
            continue
        oid = intent["order_id"]
        if oid and oid in orders:
            # Existing rows were already committed, even if their marker write crashed.
            ba.update_intent(intent["tag"], position_saved="1")
            continue
        if intent["position_saved"] == "1":
            continue                # may have been closed/sold after being recorded
        try:
            row = json.loads(intent["position_data"] or "{}")
        except (TypeError, ValueError):
            row = {}
        if not row or row.get("strategy") not in ("Momentum", "W+TT", "SIP"):
            print("! BUY %s tag %s has no recoverable position metadata; "
                  "exposure stays blocked/reserved." % (intent["symbol"], intent["tag"]))
            continue
        if row.get("symbol") != intent["symbol"] or row.get("mode") != "LIVE":
            raise ValueError("intent position metadata does not match the BUY")
        if sess is None:
            continue
        if not oid:
            found, oid, status = ba.find_order_by_tag(sess, intent["tag"])
            if not found:
                continue
            ba.update_intent(intent["tag"], state="ACCEPTED", order_id=oid,
                             status=status, note="recovered by tag")
        order = ba.check_order_status(oid, sess=sess)
        if order.get("status") is None:
            continue               # reserve until fills/status can be established
        row.update(order_id=oid, intent_tag=intent["tag"],
                   ordered_qty=int(float(intent["qty"])),
                   filled_qty_confirmed=int(_number(intent["filled_qty"])),
                   fill_avg_price=_number(intent["avg_price"]),
                   fill_avg_qty=int(_number(intent["avg_qty"])),
                   note=str(row.get("note") or "") + " | recovered AMO pending")
        row = _fill_row(row, order)
        if order["status"] in ("REJECTED", "CANCELLED", "EXPIRED") and row["filled_qty_confirmed"] == 0:
            ba.update_intent(intent["tag"], state="CLOSED", status=order["status"])
            continue
        recovered.append(row)
        orders.add(oid)
    if recovered:
        additions = pd.DataFrame(recovered)
        sp = additions if sp.empty else pd.concat([sp, additions], ignore_index=True)
        write_split(sp)
        _mark_saved(recovered)
        print("Recovered %d BUY position(s); no new order submitted." % len(recovered))
    # Retry SIP log commits after a crash too; log_buys deduplicates order IDs.
    for _, intent in ba.load_intents().iterrows():
        if intent["side"] != "BUY" or intent["position_saved"] != "1":
            continue
        try:
            row = json.loads(intent["position_data"] or "{}")
        except (TypeError, ValueError):
            continue
        if row.get("sip_id"):
            row["order_id"] = intent["order_id"]
            import sip
            sip.log_buys([row], intent["date"])
    return sp


def sync(sess):
    """Recover missing BUYs, then reconcile quantities and actual fill prices."""
    sp = recover_buys(sess)
    pend = sp[(sp["mode"] == "LIVE") & (sp["order_id"].fillna("").astype(str).ne(""))
              & sp["note"].astype(str).str.contains("pending")]
    if pend.empty:
        print("No pending AMO rows in split.csv.")
        return
    sp = sp.astype(object)      # a 0 column read as int64 must take 101.5
    for i, r in pend.iterrows():  # (pandas 3 raises on the lossy write)
        oid = str(r["order_id"]).split(".")[0]
        o = ba.check_order_status(oid, sess=sess)
        updated = _fill_row(r, o)
        for col, value in updated.items():
            sp.at[i, col] = value
        q = updated["filled_qty_confirmed"]
        st = o["status"] or o["raw"] or "?"
        if q == 0 and st in ("REJECTED", "CANCELLED", "EXPIRED"):
            import sip
            sip.mark_rejected(oid)
        print("  %-12s %s: confirmed %d, entry %.2f%s" % (
            r["symbol"], st, q, _number(updated["entry_price"]),
            " (price pending)" if updated.get("price_pending") else ""))
    write_split(sp)
    _mark_saved(sp.to_dict("records"))


# ================================================================== sells
def read_sells(path):
    """Sell sheet rows with Sell? = YES: [{symbol, product, qty}]."""
    try:
        d = pd.read_excel(path, sheet_name="Sell", header=2, dtype=str)
    except Exception:
        return []
    out = []
    for _, x in d.fillna("").iterrows():
        if str(x.get("Sell?", "")).upper().strip() != "YES":
            continue
        sym = str(x.get("Symbol", "")).upper().strip()
        try:
            q = int(float(x.get("Qty", 0)))
        except ValueError:
            q = 0
        if sym and " " not in sym and q > 0:
            out.append({"symbol": sym, "qty": q, "product": "MTF" if str(
                x.get("Product", "")).upper().strip() == "MTF" else "CNC"})
    return out


def place_sells(sess, sells, dry):
    """SELL AMOs for the Sell sheet's YES rows (checked against the demat
    right now). Needs the typed confirmation YES SELL."""
    if ds.market_open():
        print("\n! Market is open -- SELL AMOs only after 15:30.")
        return []
    try:
        dq = {h["symbol"]: float(h["qty"]) for h in ba.holdings(sess)}
    except ba.BrokerError as e:
        print("! Could not read the demat (%s) -- no SELL sent." % e)
        return []
    known = ba.symbol_map(sess)
    todo, skip = [], []
    for x in sells:
        s = x["symbol"]
        have = dq.get(s, 0) - sum(t["qty"] for t in todo if t["symbol"] == s)
        if s not in known:
            skip.append("%s (not in the %s symbol list)" % (s, sess.label))
        elif ba.sold_recently(s, sess=sess) or \
                ba.ordered_today(s, "SELL", sess=sess):
            skip.append("%s (SELL already sent)" % s)
        elif have < 1:
            skip.append("%s (not in the demat)" % s)
        else:
            todo.append(dict(x, qty=int(min(x["qty"], have))))
    if skip:
        print("SELL skipped: " + "; ".join(skip))
    if not todo:
        return []
    print("\n%s SELL AMO ORDERS -- account %s (MARKET at the next open):"
          % (sess.label.upper(), sess.client_id))
    for x in todo:
        print("  SELL %-12s %-3s qty %d" % (x["symbol"], x["product"], x["qty"]))
    if dry:
        print("(--dry-run: no SELL sent)")
        return []
    ok, msg = ba.verify_identity(sess)
    if not ok:
        print("! Account check failed: %s. No SELL sent." % msg)
        return []
    print("  %s" % msg)
    ans = input("\nType YES SELL to send these %d SELL order(s) to %s account "
                "%s: " % (len(todo), sess.label, sess.client_id))
    if " ".join(ans.upper().split()) != "YES SELL":
        print("Cancelled -- no SELL sent.")
        return []
    done = []
    sp = read_split()
    sp["note"] = sp["note"].fillna("").astype(object).astype(str)
    for x in todo:
        ok, res, status = send_one(sess, x["symbol"], x["qty"],
                                   x["product"], "SELL")
        if ok:
            print("  OK   SELL %-12s order %s (%s)" % (x["symbol"], res, status))
            m = (sp["symbol"] == x["symbol"]) & (sp["mode"] == "LIVE")
            sp.loc[m, "note"] = [str(v) + " | SELL AMO %s sent %s" % (
                res, dt.date.today()) for v in sp.loc[m, "note"]]
            done.append(x)
        else:
            print("  FAIL SELL %-12s %s" % (x["symbol"], res))
            if "DDPI" in res.upper() or "TPIN" in res.upper() or \
                    "EDIS" in res.upper() or "AUTHORI" in res.upper():
                print("  ! Broker wants demat authorisation: enable DDPI (or "
                      "do eDIS/TPIN in the broker app) and try again.")
    if done:
        write_split(sp)
        print("SELL sent: %d. The journal closes them after the fill (next rb)."
              % len(done))
    return done


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
    if not take_lock():
        print("! Another rbtrack is running for this account -- wait for it "
              "to finish (nothing sent).")
        sys.exit(1)
    if "--resolve" in a:
        k = a.index("--resolve")
        tag = a[k + 1] if k + 1 < len(a) else ""
        how = a[k + 2].lower() if k + 2 < len(a) else ""
        if how not in ("placed", "not-placed"):
            print("Use: rbtrack --resolve TAG placed|not-placed [ORDER_ID]")
            sys.exit(1)
        oid = a[k + 3] if k + 3 < len(a) else ""
        print("Resolved %s as %s." % (tag, how) if ba.resolve_intent(
            tag, how == "placed", oid) else "No intent with tag %s." % tag)
        return
    op = ba.open_intents()
    if len(op):
        print("!! %d order(s) with UNKNOWN status (these stocks are blocked "
              "until resolved):" % len(op))
        for _, r in op.iterrows():
            print("   %s %s %s x%s  tag %s  (%s)" % (r["date"], r["side"],
                                                   r["symbol"], r["qty"],
                                                   r["tag"], r["state"]))
        print("   Check the broker app, then: rbtrack --resolve TAG "
              "placed|not-placed")
    sess = ms.get_session()
    if sess is not None and not dry:
        recover_buys(sess)          # commit recovered exposure before any new planning
    if "--clear-paper" in a:                # PAPER mode removed 27 Sep
        sp = read_split()
        n = int((sp["mode"] == "PAPER").sum())
        if n:
            write_split(sp[sp["mode"] != "PAPER"])
        import journal
        j = journal.load()
        k = int((j["mode"] == "PAPER").sum())
        if k:
            journal.save(j[j["mode"] != "PAPER"])
        print("Removed %d PAPER row(s) from split.csv (backup: "
              "split_backup.csv) and %d from the journal." % (n, k))
        account.banner(acc)
        return
    if "--sold" in a:
        k = a.index("--sold")
        sym = a[k + 1].upper() if k + 1 < len(a) else ""
        price = None
        if k + 2 < len(a):
            try:
                price = float(a[k + 2].replace(",", ""))
            except ValueError:
                price = None
        day = a[a.index("--date") + 1] if "--date" in a else today_str()
        mode = "PAPER" if "--paper" in a else "LIVE"
        if not sym:
            print("Use: rbtrack --sold SYMBOL [PRICE] [--date YYYY-MM-DD] "
                  "[--paper]")
            sys.exit(1)
        px = {}
        if price is None:
            got = prices(sess, [sym])
            px = {sym: got[sym][0]} if sym in got else {}
        import journal
        print(journal.close_manual(sym, price, day, mode, acc.broker, px))
        account.banner(acc)
        return
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
    rd = pf.report_date(path)
    if rd != today:
        print("\n!! %s is from %s, NOT today (%s): Buy_Planner / Sell picks are "
              "old. Run rb first." % (os.path.basename(path), rd or "?",
                                      today))
    try:                            # copy in Google Drive (Sheets edits)
        import drive_copy
        drive_copy.pull(path)       # Action picks made in Google Sheets
    except ImportError:
        pass
    rows = action_rows(path)              # old files only (6 Oct: gone)
    prow, _ = planner_rows(path)          # BUY / MTF / WATCH = Buy_Planner
    if len(prow):
        tick = rows["Ticker"].astype(str).str.upper()
        dup = sorted(set(prow["Ticker"]) & set(tick))
        if dup:
            print("  Buy_Planner wins over Actions for: %s" % ", ".join(dup))
            rows = rows[~tick.isin(dup)]
        rows = pd.concat([rows, prow], ignore_index=True)
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
    import sip
    probs = sip.read_sheet(path)            # your SIP sheet -> sip.csv
    for pr in probs:
        print("! SIP: %s" % pr)
    sdue = sip.due(today, early=ds.now_ist().hour < 9)
    import settings
    trading = settings.read_dashboard(path)
    sells = read_sells(path)
    if trading != "ON":
        if len(rows) or sdue or sells:
            print("\n!! TRADING is OFF (Dashboard, cell B2) -> NO order sent "
                  "(BUY %d, SIP due %d, SELL YES %d wait)."
                  % (len(rows), len(sdue), len(sells)))
            print("   To trade: Dashboard B2 = ON, save, run rbtrack again.")
        account.banner(acc)
        return
    if sells:
        if no_orders:
            print("! --no-orders: SELL rows skipped (sell in the broker app).")
        elif not sess:
            print("! SELL needs a valid broker token.")
        else:
            place_sells(sess, sells, dry)
    if rows.empty and not sdue:
        if not len(watch) and not sells:
            print("Nothing to do: no BUY / MTF in the Buy_Planner sheet, no "
                  "SIP due, no SELL = YES (%s)." % os.path.basename(path))
        account.banner(acc)
        return
    sp = read_split()
    px = prices(sess, sorted({str(t).upper().strip() for t in rows["Ticker"]}
                             | {x["symbol"] for x in sdue}))
    slot = None
    if sess and len(rows):
        val, how = ba.account_value(sess)
        slot = ms.slot_for(val)
        print("Per-stock slot: Rs %s = account value %s / %d%s" % (
            format(int(slot), ","), "Rs " + format(int(val), ",") if val
            else "unknown", ms.SLOTS, " (%s)" % how if val else
            " -> Rs %s default (%s)" % (format(int(slot), ","), how)))
    new, skip = plan(rows, px, sp, sess, slot) if len(rows) else ([], [])

    def lev_of(sym, price):
        lev, note = ba.mtf_leverage(sess, sym, price)
        return (lev, note) if lev else (float(MTF_LEVERAGE),
                                        "MTF %gx ASSUMED (%s)"
                                        % (MTF_LEVERAGE, note))
    snew, sskip = sip.plan_orders(sdue, px, lev_of, today)
    done = {x["symbol"] for x in snew
            if ba.ordered_today(x["symbol"], sess=sess)}
    for x in snew:
        if x["symbol"] in done:
            sskip.append("SIP %s (order already placed today)" % x["symbol"])
    snew = [x for x in snew if x["symbol"] not in done]
    if snew:
        print("SIP due today: " + ", ".join(
            "%s %s x%d (own Rs %s)" % (x["sip_id"], x["product"], x["shares"],
                                      format(int(x["own"]), ","))
            for x in snew))
    new += snew
    skip += sskip
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
                "swing_qty", "investing_qty", "entry_price", "order_id"]]
          .to_string(index=False))
    if dry:
        print("\n(--dry-run: nothing written)")
        return
    write_split(pd.concat([sp, show.reindex(columns=COLUMNS + TRACKING_COLS)],
                          ignore_index=True))
    _mark_saved(add)
    sip.log_buys(add, today)
    print("\nSaved %d row(s) (previous copy: split_backup.csv)." % len(add))
    if any("free source" in x["note"] for x in add):
        print("! Some prices came from the free source, not the broker.")
    if live:
        print("After tomorrow's open run:  rbtrack --sync   (real fill prices)")
    account.banner(acc)


if __name__ == "__main__":
    main()
