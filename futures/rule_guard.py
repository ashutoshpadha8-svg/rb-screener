"""
Topstep Rule Guard - watches your account while YOU trade manually and alerts BEFORE a rule breaks.
It never places, changes or cancels orders. Read-only.

Setup (once):
  pip3 install requests
  Put your TopstepX username on line 1 and API key on line 2 of:
    ~/Desktop/RB_Screener/futures/topstep_login.txt
  (NEVER put these in a .py file, never print or share them.)

Commands:
  python3 rule_guard.py demo                         # see sample alerts, no API needed
  python3 rule_guard.py watch --since 2026-10-01     # live watch (since = day the account started)
  python3 rule_guard.py check MNQ 10 20 --since 2026-10-01
                                                     # pre-trade: 10 MNQ with 20-point stop -> GO / NO-GO

Rules checked (Topstep 50K Trading Combine, verified Sep 2026 - re-check help.topstep.com if Topstep changes them):
  - Max Loss Limit $2,000, trails end-of-day balance, locks at $50,000. Hit even on unrealized P&L = account fails.
  - Max position 5 minis / 50 micros.
  - Flat by 3:10 PM CT (Topstep trading day = 5:00 PM CT to 3:10 PM CT).
  - Consistency: best day <= 55% of total profit, else profit target goes up.
  - Profit target $3,000.
Your own rules (edit PERSONAL below): daily loss limit, max risk per trade, stop must exist.
"""
import argparse
import datetime as dt
import os
import re
import subprocess
import sys
import time

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    sys.exit("Python 3.9+ needed")

CT = ZoneInfo("America/Chicago")
IST = ZoneInfo("Asia/Kolkata")

RULES = {
    "name": "Topstep 50K Trading Combine",
    "start_balance": 50000.0,
    "mll": 2000.0,
    "target": 3000.0,
    "max_micros": 50,          # 1 mini = 10 micros
    "consistency": 0.55,
    "flat_by": dt.time(15, 10),   # CT
    "day_starts": dt.time(17, 0),  # CT
}

PERSONAL = {
    "daily_loss_limit": 800.0,     # your own stop for the day (Topstep doesn't force one). None to switch off
    "max_risk_per_trade": 300.0,   # $ lost if the stop is hit
    "require_stop": True,          # every open position must have a stop order working
}

API = "https://api.topstepx.com"
HERE = os.path.dirname(os.path.abspath(__file__))
LOGIN_FILE = os.path.join(HERE, "topstep_login.txt")

# levels
INFO, WARN, DANGER, BREACH = "INFO", "WARN", "DANGER", "BREACH"
ORDER_STOP_TYPES = {3, 4, 5}      # StopLimit, Stop, TrailingStop
LONG, SHORT = 1, 2                 # PositionType
BID, ASK = 0, 1                    # OrderSide


# ---------------------------------------------------------------- helpers

def trading_day(ts_ct):
    """Topstep trading day: anything after 5 PM CT counts for the next calendar day."""
    d = ts_ct.date()
    if ts_ct.time() >= RULES["day_starts"]:
        d += dt.timedelta(days=1)
    return d


def parse_ts(s):
    s = s.replace("Z", "+00:00")
    s = re.sub(r"\.(\d{6})\d+", r".\1", s)   # .NET can send 7 fraction digits
    return dt.datetime.fromisoformat(s)


def root_of(contract_id):
    parts = contract_id.split(".")
    return parts[3] if len(parts) > 3 else contract_id


def is_micro(contract_id):
    return root_of(contract_id).startswith("M")


def micro_equiv(contract_id, size):
    return size if is_micro(contract_id) else size * 10


def daily_net(trades):
    """trades from /api/Trade/search -> {trading_day: net P&L after fees}"""
    out = {}
    for t in trades:
        if t.get("voided"):
            continue
        d = trading_day(parse_ts(t["creationTimestamp"]).astimezone(CT))
        out[d] = out.get(d, 0.0) + (t.get("profitAndLoss") or 0.0) - (t.get("fees") or 0.0)
    return out


def mll_floor(daily, today, start, mll):
    """EOD trailing: highest closing balance of completed days minus MLL, never above start balance."""
    bal, peak = start, start
    for d in sorted(daily):
        if d >= today:
            break
        bal += daily[d]
        peak = max(peak, bal)
    return min(peak - mll, start)


def point_value(p):
    return p["tick_value"] / p["tick_size"]


# ---------------------------------------------------------------- the rule engine (pure, testable)

def evaluate(snap, now_ct, rules=RULES, personal=PERSONAL):
    """snap = {balance, positions:[{contract, type, size, avg, last, tick_size, tick_value}],
               orders:[{contract, type, side, size, stop}], daily:{day: net}}
    returns list of (level, key, message)"""
    alerts = []
    today = trading_day(now_ct)
    start, mll = rules["start_balance"], rules["mll"]
    floor = mll_floor(snap["daily"], today, start, mll)

    unreal = 0.0
    for p in snap["positions"]:
        sgn = 1 if p["type"] == LONG else -1
        unreal += sgn * (p["last"] - p["avg"]) * p["size"] * point_value(p)
    equity = snap["balance"] + unreal
    room = equity - floor
    today_net = snap["daily"].get(today, 0.0) + unreal

    # 1. Max Loss Limit
    if room <= 0:
        alerts.append((BREACH, "mll", "MAX LOSS LIMIT HIT. Equity $%.0f <= floor $%.0f. Account liquidated." % (equity, floor)))
    elif room < 0.25 * mll:
        alerts.append((DANGER, "mll", "MLL se sirf $%.0f door! Position kam karo / band karo. (equity $%.0f, floor $%.0f)" % (room, equity, floor)))
    elif room < 0.5 * mll:
        alerts.append((WARN, "mll", "MLL buffer aadha bacha: $%.0f (floor $%.0f). Size chhota rakho." % (room, floor)))

    # 2. Personal daily loss limit
    dll = personal.get("daily_loss_limit")
    if dll:
        if today_net <= -dll:
            alerts.append((DANGER, "dll", "Aaj ka loss $%.0f - aapka daily limit $%.0f cross. AAJ TRADING BAND." % (-today_net, dll)))
        elif today_net <= -0.75 * dll:
            alerts.append((WARN, "dll", "Aaj ka loss $%.0f - daily limit $%.0f ke 75%% pe." % (-today_net, dll)))

    # 3. Position size
    size = sum(micro_equiv(p["contract"], p["size"]) for p in snap["positions"])
    working = 0
    for o in snap["orders"]:
        if o["type"] not in ORDER_STOP_TYPES:   # entry orders that could add size
            working += micro_equiv(o["contract"], o["size"])
    if size > rules["max_micros"]:
        alerts.append((BREACH, "size", "SIZE LIMIT TOOTA: %d micro-equiv > %d. Turant kam karo." % (size, rules["max_micros"])))
    elif size + working > rules["max_micros"]:
        alerts.append((DANGER, "size", "Open + pending orders = %d micro-equiv > limit %d. Pending order fill hua to violation." % (size + working, rules["max_micros"])))
    elif size >= 0.8 * rules["max_micros"]:
        alerts.append((WARN, "size", "Size %d / %d micro-equiv." % (size, rules["max_micros"])))

    # 4. Stops: exist, and not below MLL / daily limit if hit
    loss_at_stops = 0.0
    for p in snap["positions"]:
        exit_side = ASK if p["type"] == LONG else BID
        stops = [o for o in snap["orders"] if o["contract"] == p["contract"]
                 and o["type"] in ORDER_STOP_TYPES and o["side"] == exit_side and o.get("stop")]
        covered = sum(o["size"] for o in stops)
        name = root_of(p["contract"])
        if personal.get("require_stop") and covered < p["size"]:
            alerts.append((DANGER, "nostop_" + name, "%s position (%d) pe stop nahi hai (covered %d). Abhi stop lagao." % (name, p["size"], covered)))
        sgn = 1 if p["type"] == LONG else -1
        pv = point_value(p)
        worst = min((o["stop"] for o in stops), default=None) if sgn > 0 else max((o["stop"] for o in stops), default=None)
        if worst is not None:
            pnl_at_stop = sgn * (worst - p["avg"]) * p["size"] * pv
            loss_at_stops += min(0.0, sgn * (worst - p["last"]) * p["size"] * pv)
            if pnl_at_stop < -personal.get("max_risk_per_trade", 1e9):
                alerts.append((WARN, "risk_" + name, "%s: stop hit hua to $%.0f loss > aapka max $%.0f per trade." % (name, -pnl_at_stop, personal["max_risk_per_trade"])))
    if snap["positions"] and equity + loss_at_stops <= floor:
        alerts.append((DANGER, "stop_mll", "Stop hit hua to equity $%.0f -> MLL floor $%.0f ke neeche. Stop tight karo ya size kam karo." % (equity + loss_at_stops, floor)))

    # 5. Time: flat by 3:10 PM CT
    t = now_ct.time()
    if snap["positions"] or snap["orders"]:
        mins_left = (dt.datetime.combine(now_ct.date(), rules["flat_by"]) - now_ct.replace(tzinfo=None)).total_seconds() / 60
        if rules["flat_by"] <= t < rules["day_starts"]:
            if snap["positions"]:
                alerts.append((BREACH, "time", "3:10 PM CT ke baad position khuli hai! Turant close karo."))
        elif 0 < mins_left <= 3:
            alerts.append((DANGER, "time", "%.0f min mein 3:10 PM CT - ABHI flat ho jao, pending orders cancel karo." % mins_left))
        elif 0 < mins_left <= 15:
            alerts.append((WARN, "time", "%.0f min baaki 3:10 PM CT close tak. Naya trade mat lo." % mins_left))

    # 6. Target and consistency
    total = equity - start
    days = dict(snap["daily"])
    days[today] = today_net
    best = max([v for v in days.values()] + [0.0])
    need = max(rules["target"], best / rules["consistency"]) if best > 0 else rules["target"]
    if total >= need:
        alerts.append((INFO, "target", "TARGET DONE: profit $%.0f, best day $%.0f (<= %d%%). Positions band karo, aur trade mat lo." % (total, best, rules["consistency"] * 100)))
    elif today_net > rules["consistency"] * rules["target"]:
        alerts.append((WARN, "consistency", "Aaj ka profit $%.0f > $%.0f: consistency ki wajah se target ab $%.0f ho gaya. Aaj band karna behtar." % (today_net, rules["consistency"] * rules["target"], need)))
    elif today_net > 0.8 * rules["consistency"] * rules["target"]:
        alerts.append((INFO, "consistency", "Aaj ka profit $%.0f - $%.0f ke baad consistency target badhayega." % (today_net, rules["consistency"] * rules["target"])))

    return alerts


def pretrade(snap, now_ct, contract, qty, stop_pts, tick_size, tick_value, rules=RULES, personal=PERSONAL):
    """Would this new trade break anything if the stop is hit? Returns (ok, reasons)."""
    reasons = []
    today = trading_day(now_ct)
    floor = mll_floor(snap["daily"], today, rules["start_balance"], rules["mll"])
    unreal = sum((1 if p["type"] == LONG else -1) * (p["last"] - p["avg"]) * p["size"] * point_value(p)
                 for p in snap["positions"])
    equity = snap["balance"] + unreal
    risk = qty * stop_pts * tick_value / tick_size + qty * 2 * 0.75   # + fees approx
    size_now = sum(micro_equiv(p["contract"], p["size"]) for p in snap["positions"])
    size_new = size_now + micro_equiv(contract, qty)
    today_net = snap["daily"].get(today, 0.0) + unreal

    if size_new > rules["max_micros"]:
        reasons.append("Size %d micro-equiv > limit %d" % (size_new, rules["max_micros"]))
    if equity - risk <= floor + 100:
        reasons.append("Stop hit hua to equity $%.0f -> MLL floor $%.0f ke paas/neeche" % (equity - risk, floor))
    if risk > personal.get("max_risk_per_trade", 1e9):
        reasons.append("Risk $%.0f > aapka max per trade $%.0f" % (risk, personal["max_risk_per_trade"]))
    dll = personal.get("daily_loss_limit")
    if dll and today_net - risk < -dll:
        reasons.append("Stop hit hua to aaj ka loss $%.0f > daily limit $%.0f" % (-(today_net - risk), dll))
    mins_left = (dt.datetime.combine(now_ct.date(), rules["flat_by"]) - now_ct.replace(tzinfo=None)).total_seconds() / 60
    if rules["flat_by"] <= now_ct.time() < rules["day_starts"]:
        reasons.append("Market 3:10 PM CT ke baad - Topstep trading day band")
    elif 0 < mins_left <= 15:
        reasons.append("Sirf %.0f min baaki 3:10 PM CT tak" % mins_left)
    info = "Risk if stop hit: $%.0f | MLL room now: $%.0f | after stop: $%.0f" % (risk, equity - floor, equity - risk - floor)
    return (not reasons), reasons, info


# ---------------------------------------------------------------- alerts

class Alerter:
    COLORS = {INFO: "\033[36m", WARN: "\033[33m", DANGER: "\033[31m", BREACH: "\033[41;97m"}
    REPEAT = {INFO: 600, WARN: 120, DANGER: 30, BREACH: 15}   # seconds before the same alert repeats

    def __init__(self):
        self.last = {}

    def send(self, level, key, msg):
        now = time.time()
        if now - self.last.get((level, key), 0) < self.REPEAT[level]:
            return
        self.last[(level, key)] = now
        stamp = dt.datetime.now(IST).strftime("%H:%M:%S IST")
        print("%s%s [%s] %s\033[0m" % (self.COLORS[level], stamp, level, msg), flush=True)
        if sys.platform == "darwin":
            safe = msg.replace('"', "'")
            subprocess.run(["osascript", "-e", 'display notification "%s" with title "Rule Guard: %s" sound name "Sosumi"' % (safe, level)],
                           check=False, capture_output=True)
            if level in (DANGER, BREACH):
                subprocess.run(["say", "Rule guard. " + level.lower() + ". " + key.split("_")[0]], check=False)


# ---------------------------------------------------------------- TopstepX API (read-only)

class TopstepX:
    def __init__(self):
        import requests
        self.s = requests.Session()
        self.token = None
        self.contracts = {}

    def login(self):
        if not os.path.exists(LOGIN_FILE):
            sys.exit("Login file missing: %s (line 1 username, line 2 API key)" % LOGIN_FILE)
        with open(LOGIN_FILE) as f:
            lines = [x.strip() for x in f.read().splitlines() if x.strip()]
        if len(lines) < 2:
            sys.exit("topstep_login.txt needs 2 lines: username, then API key")
        r = self.s.post(API + "/api/Auth/loginKey", json={"userName": lines[0], "apiKey": lines[1]}, timeout=15).json()
        if not r.get("success"):
            sys.exit("Login failed (errorCode %s). Check username / API key / API subscription." % r.get("errorCode"))
        self.token = r["token"]

    def post(self, path, body):
        for attempt in range(3):
            if not self.token:
                self.login()
            r = self.s.post(API + path, json=body, headers={"Authorization": "Bearer " + self.token}, timeout=15)
            if r.status_code == 401:
                self.token = None
                continue
            if r.status_code == 429:
                time.sleep(5)
                continue
            r.raise_for_status()
            j = r.json()
            if not j.get("success", True):
                raise RuntimeError("%s failed: errorCode %s" % (path, j.get("errorCode")))
            return j
        raise RuntimeError("%s failed after retries" % path)

    def contract(self, cid):
        if cid not in self.contracts:
            self.contracts[cid] = self.post("/api/Contract/searchById", {"contractId": cid})["contract"]
        return self.contracts[cid]

    def find_contract(self, symbol):
        j = self.post("/api/Contract/search", {"searchText": symbol, "live": False})
        for c in j.get("contracts", []):
            if c.get("activeContract", True) and root_of(c["id"]) == symbol.upper():
                return c
        sys.exit("Contract %s not found" % symbol)

    def last_price(self, cid):
        now = dt.datetime.now(dt.timezone.utc)
        j = self.post("/api/History/retrieveBars", {
            "contractId": cid, "live": False, "unit": 2, "unitNumber": 1, "limit": 1, "includePartialBar": True,
            "startTime": (now - dt.timedelta(hours=2)).isoformat(), "endTime": now.isoformat()})
        bars = j.get("bars") or []
        return bars[0]["c"] if bars else None

    def account(self, name=None):
        accs = self.post("/api/Account/search", {"onlyActiveAccounts": True})["accounts"]
        if name:
            accs = [a for a in accs if a["name"] == name]
        if not accs:
            sys.exit("No active account found")
        if len(accs) > 1 and not name:
            print("Multiple accounts, using %s. Use --account to choose: %s" % (accs[0]["name"], [a["name"] for a in accs]))
        return accs[0]

    def snapshot(self, acc_name, since):
        acc = self.account(acc_name)
        aid = acc["id"]
        pos = self.post("/api/Position/searchOpen", {"accountId": aid}).get("positions", [])
        orders = self.post("/api/Order/searchOpen", {"accountId": aid}).get("orders", [])
        trades = self.post("/api/Trade/search", {"accountId": aid, "startTimestamp": since.isoformat()}).get("trades", [])
        positions = []
        for p in pos:
            c = self.contract(p["contractId"])
            last = self.last_price(p["contractId"]) or p["averagePrice"]
            positions.append({"contract": p["contractId"], "type": p["type"], "size": p["size"],
                              "avg": p["averagePrice"], "last": last,
                              "tick_size": c["tickSize"], "tick_value": c["tickValue"]})
        return {"account": acc["name"], "balance": acc["balance"], "positions": positions,
                "orders": [{"contract": o["contractId"], "type": o["type"], "side": o["side"],
                            "size": o["size"], "stop": o.get("stopPrice")} for o in orders],
                "daily": daily_net(trades)}


# ---------------------------------------------------------------- commands

def cmd_watch(args):
    api, alerter = TopstepX(), Alerter()
    since = dt.datetime.combine(args.since, dt.time(0), tzinfo=CT) - dt.timedelta(hours=7)
    print("Rule Guard ON - %s. Read-only, har %ds check. Ctrl+C se band." % (RULES["name"], args.every))
    while True:
        try:
            snap = api.snapshot(args.account, since)
            now = dt.datetime.now(CT)
            alerts = evaluate(snap, now)
            for a in alerts:
                alerter.send(*a)
            if args.verbose or not alerts:
                today = trading_day(now)
                floor = mll_floor(snap["daily"], today, RULES["start_balance"], RULES["mll"])
                print("%s ok | bal $%.0f | floor $%.0f | positions %d" %
                      (dt.datetime.now(IST).strftime("%H:%M:%S"), snap["balance"], floor, len(snap["positions"])), end="\r")
        except KeyboardInterrupt:
            raise
        except Exception as e:   # network blips must not kill the guard
            alerter.send(WARN, "guard", "Guard ko data nahi mila (%s). Platform pe khud check karo." % type(e).__name__)
        time.sleep(args.every)


def cmd_check(args):
    api = TopstepX()
    since = dt.datetime.combine(args.since, dt.time(0), tzinfo=CT) - dt.timedelta(hours=7)
    snap = api.snapshot(args.account, since)
    c = api.find_contract(args.symbol)
    ok, reasons, info = pretrade(snap, dt.datetime.now(CT), c["id"], args.qty, args.stop_points, c["tickSize"], c["tickValue"])
    print(info)
    print("\033[32mGO\033[0m" if ok else "\033[31mNO-GO\033[0m")
    for r in reasons:
        print("  - " + r)


def demo_snapshots():
    d0 = dt.date(2026, 10, 5)
    mnq = "CON.F.US.MNQ.Z26"
    base = {"tick_size": 0.25, "tick_value": 0.5}
    return [
        ("Normal trade, stop laga hai", dt.datetime(2026, 10, 7, 10, 0, tzinfo=CT), {
            "balance": 50400.0, "daily": {d0: 400.0},
            "positions": [dict(base, contract=mnq, type=LONG, size=5, avg=20000.0, last=20010.0)],
            "orders": [{"contract": mnq, "type": 4, "side": ASK, "size": 5, "stop": 19980.0}]}),
        ("Bina stop, MLL ke paas", dt.datetime(2026, 10, 7, 11, 0, tzinfo=CT), {
            "balance": 49000.0, "daily": {d0: -600.0, dt.date(2026, 10, 6): -400.0},
            "positions": [dict(base, contract=mnq, type=SHORT, size=10, avg=20000.0, last=20040.0)],
            "orders": []}),
        ("3:05 PM CT, position khuli", dt.datetime(2026, 10, 7, 15, 5, tzinfo=CT), {
            "balance": 50200.0, "daily": {d0: 200.0},
            "positions": [dict(base, contract=mnq, type=LONG, size=4, avg=20000.0, last=20005.0)],
            "orders": [{"contract": mnq, "type": 4, "side": ASK, "size": 4, "stop": 19990.0}]}),
        ("Ek bada din - consistency", dt.datetime(2026, 10, 7, 12, 0, tzinfo=CT), {
            "balance": 52000.0, "daily": {d0: 300.0, dt.date(2026, 10, 7): 1700.0},
            "positions": [], "orders": []}),
    ]


def cmd_demo(args):
    alerter = Alerter()
    for title, now, snap in demo_snapshots():
        print("\n=== %s (%s CT)" % (title, now.strftime("%H:%M")))
        alerts = evaluate(snap, now)
        if not alerts:
            print("  sab theek - koi alert nahi")
        for a in alerts:
            alerter.send(*a)
        ok, reasons, info = pretrade(snap, now, "CON.F.US.MNQ.Z26", 10, 30, 0.25, 0.5)
        print("  Pre-trade 10 MNQ, 30pt stop: %s | %s" % ("GO" if ok else "NO-GO: " + "; ".join(reasons), info))


def main():
    ap = argparse.ArgumentParser(description="Topstep Rule Guard (read-only)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demo")
    since_help = "Account start date YYYY-MM-DD (needed for correct MLL)"
    w = sub.add_parser("watch")
    w.add_argument("--since", type=dt.date.fromisoformat, required=True, help=since_help)
    w.add_argument("--account", default=None)
    w.add_argument("--every", type=int, default=5)
    w.add_argument("--verbose", action="store_true")
    c = sub.add_parser("check")
    c.add_argument("symbol")
    c.add_argument("qty", type=int)
    c.add_argument("stop_points", type=float)
    c.add_argument("--since", type=dt.date.fromisoformat, required=True, help=since_help)
    c.add_argument("--account", default=None)
    args = ap.parse_args()
    {"demo": cmd_demo, "watch": cmd_watch, "check": cmd_check}[args.cmd](args)


if __name__ == "__main__":
    main()
