"""rbmtf for ANGEL / ZERODHA (RB 9 Oct: "har broker ke liye honna chahiye").

Dhan has trade-history and ledger APIs, so mtf_check.build() reconstructs lots and
interest by itself. Angel One and Zerodha do NOT (trade book = today only, no ledger
API), so this builds the same report input R from what those APIs DO give:

  * MTF stocks + qty + average price      broker_api.mtf_holdings (READ-ONLY GETs)
  * price                                 mtf_check.quotes (NSE official first)
  * current loan                          --loan (broker app) ; Zerodha: qty x avg - initial_margin
  * buy date per stock                    --buy-date SYM:YYYY-MM-DD, remembered per account
  * unpaid interest                       --unpaid-interest ; else ESTIMATE since the last billing date

Nothing is invented: a missing loan / buy date stays UNKNOWN and is printed with the
exact command that fills it. No order, no ledger/statement claim.
"""
import datetime as dt
import json
import os

from mtf_check import Num, VERIFIED, ESTIMATED, UNKNOWN, quotes, _finite

INPUTS_FILE = "mtf_inputs.json"          # accounts/<..>/data/ : buy dates you typed once


def parse_pairs(value, kind):
    """'TCS:52,INFY:10@1500' (kind 'mtf') or 'TCS:2025-11-24' (kind 'date')."""
    out = {}
    for part in [x.strip() for x in str(value or "").split(",") if x.strip()]:
        if ":" not in part:
            raise ValueError("%s: use SYMBOL:%s" % (part, "QTY" if kind == "mtf" else "YYYY-MM-DD"))
        sym, rest = [x.strip() for x in part.split(":", 1)]
        sym = sym.upper()
        if not sym:
            raise ValueError("empty symbol in " + part)
        if kind == "date":
            try:
                out[sym] = dt.date.fromisoformat(rest).isoformat()
            except ValueError:
                raise ValueError("%s: date must be YYYY-MM-DD" % part)
        else:
            qty, _, avg = rest.partition("@")
            try:
                q = float(qty)
                a = float(avg) if avg else None
            except ValueError:
                raise ValueError("%s: use SYMBOL:QTY or SYMBOL:QTY@AVG" % part)
            if not (q > 0 and q == int(q)) or (a is not None and not a > 0):
                raise ValueError("%s: qty must be a whole number > 0, avg > 0" % part)
            out[sym] = (q, a)
    return out


def load_inputs(path):
    try:
        with open(path) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_inputs(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1, sort_keys=True)
    os.replace(tmp, path)


def billing_start(broker, today):
    """Start of the current interest-debit period (ASSUMPTION, printed as such):
    Angel One debits MTF interest fortnightly (1st / 16th); Zerodha monthly (1st)."""
    if broker == "ANGEL":
        return today.replace(day=16) if today.day >= 16 else today.replace(day=1)
    return today.replace(day=1)


def build_generic(args, sess, today, data_dir, holdings_fn=None, quotes_fn=None):
    """Same R shape that mtf_portfolio_report.calculate/write_report/print_report read."""
    import broker_api as ba
    holdings_fn = holdings_fn or ba.mtf_holdings
    quotes_fn = quotes_fn or quotes
    broker = sess.broker
    src = {}
    try:
        mtf = holdings_fn(sess)
        src["holdings"] = (VERIFIED, "%s MTF holdings (%d stock(s))" % (broker, len(mtf)))
    except ba.AuthError:
        raise
    except Exception as e:
        mtf = {}
        src["holdings"] = (UNKNOWN, "%s MTF holdings failed: %s" % (broker, type(e).__name__))
    manual = parse_pairs(getattr(args, "mtf", None), "mtf")
    for sym, (q, a) in manual.items():
        base = mtf.get(sym, {})
        avg = a if a is not None else base.get("avg_price")
        mtf[sym] = dict(qty=q, avg_price=avg, own_margin=None, source="typed --mtf")
    if manual:
        src["holdings"] = (ESTIMATED, src["holdings"][1] + "; --mtf override for " + ", ".join(sorted(manual)))

    # buy dates: typed now (saved) or remembered for the SAME qty
    path = os.path.join(data_dir, INPUTS_FILE) if data_dir else None
    saved = load_inputs(path) if path else {}
    typed = parse_pairs(getattr(args, "buy_date", None), "date")
    for sym, d in typed.items():
        if sym not in mtf:
            raise ValueError("--buy-date %s: not an MTF stock of this account" % sym)
        if dt.date.fromisoformat(d) > today:
            raise ValueError("--buy-date %s: date is in the future" % sym)
        saved[sym] = {"date": d, "qty": mtf[sym]["qty"]}
    if typed and path:
        os.makedirs(data_dir, exist_ok=True)
        save_inputs(path, saved)

    syms = sorted(mtf)
    px = quotes_fn(sess, syms) if syms else {}
    rows, lots, missing_dates = [], {}, []
    for sym in syms:
        h = mtf[sym]
        q, avg = h["qty"], h.get("avg_price")
        cost = Num(q * avg, ESTIMATED, "broker average price x qty") if _finite(avg) and avg > 0 \
            else Num(None, UNKNOWN, "average price missing")
        p = px.get(sym)
        rows.append({"Symbol": sym, "Qty": q, "Open cost (Rs)": cost,
                     "Price": p[0] if p else None, "Price source": p[2] if p else "UNKNOWN",
                     "Inventory status": ESTIMATED,
                     "Value (Rs)": Num(q * p[0], p[1], p[2]) if p else Num(None, UNKNOWN, "price missing")})
        s = saved.get(sym)
        if s and abs(float(s.get("qty", -1)) - q) < 1e-9 and cost.known:
            lots[sym] = [[s["date"], q, avg, 0]]
        else:
            missing_dates.append(sym)
            if s:
                src["buy_date_" + sym] = (UNKNOWN, "qty changed since --buy-date was saved; type it again")
    holdings_ok = src["holdings"][0] != UNKNOWN
    costs = [r["Open cost (Rs)"] for r in rows]
    open_cost = Num(sum(c.value for c in costs), ESTIMATED, "sum of broker averages") \
        if costs and all(c.known for c in costs) else Num(None, UNKNOWN, "a cost is missing") if costs \
        else Num(0.0, VERIFIED, "no MTF stock") if holdings_ok \
        else Num(None, UNKNOWN, "holdings not read -- no zero-position conclusion")

    # loan
    if getattr(args, "loan", None) is not None:
        loan = Num(args.loan, VERIFIED, "typed (--loan)")
    elif rows and all(mtf[s].get("own_margin") is not None for s in syms) and open_cost.known:
        own = sum(mtf[s]["own_margin"] for s in syms)
        loan = Num(round(open_cost.value - own, 2), ESTIMATED,
                   "%s: cost - initial margin from holdings (check app's MTF funded amount)" % broker)
    elif not rows and holdings_ok:
        loan = Num(0.0, VERIFIED, "no MTF stock")
    elif not holdings_ok:
        loan = Num(None, UNKNOWN, "holdings not read")
    else:
        loan = Num(None, UNKNOWN, "%s API has no loan figure: rbmtf --loan <MTF funded amount from the app>" % broker)

    # unpaid interest
    rate = args.rate
    if getattr(args, "unpaid_interest", None) is not None:
        unpaid = Num(args.unpaid_interest, VERIFIED, "typed (--unpaid-interest)")
        src["ledger"] = (VERIFIED, "unpaid interest typed")
    elif loan.known:
        start = billing_start(broker, today)
        days = (today - start).days
        unpaid = Num(round(loan.value * rate * days / 365, 2), ESTIMATED,
                     "%d days since %s (assumed last %s interest debit) x loan x %.2f%%" %
                     (days, start, "fortnightly" if broker == "ANGEL" else "monthly", rate * 100))
        src["ledger"] = (ESTIMATED, "no %s ledger API; unpaid interest estimated" % broker)
    else:
        unpaid = Num(None, UNKNOWN, "needs the loan")
        src["ledger"] = (UNKNOWN, "no ledger API and no loan")
    if missing_dates:
        src["buy_dates"] = (UNKNOWN, "buy date missing for %s: rbmtf --buy-date %s" %
                            (", ".join(missing_dates), ",".join("%s:YYYY-MM-DD" % s for s in missing_dates)))
    vals = [r["Value (Rs)"] for r in rows]
    if not rows and loan.known:
        exit_cash = Num(0.0, VERIFIED, "no MTF stock")
    elif rows and loan.known and unpaid.known and all(v.known for v in vals):
        exit_cash = Num(sum(v.value for v in vals) - loan.value - unpaid.value, ESTIMATED,
                        "value - loan - unpaid interest, BEFORE sell charges (net per stock in section 3)")
    else:
        exit_cash = Num(None, UNKNOWN, loan.note if not loan.known else "price or unpaid interest missing")
    return {"src": src, "rows": rows, "loan": loan, "unpaid": unpaid, "open_cost_num": open_cost,
            "current_lots": lots, "fifo": {"lots": lots}, "exit": exit_cash,
            "init_cash": Num(getattr(args, "own_cash", None), VERIFIED, "typed")
            if getattr(args, "own_cash", None) is not None else Num(None, UNKNOWN, "needs --own-cash"),
            "generic_missing": missing_dates}
