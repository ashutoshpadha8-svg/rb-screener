#!/usr/bin/env python3
"""
ACCOUNT ISOLATION  --  one folder per broker account
====================================================

Every live script (daily_screener, momentum_screener, fundamentals,
auto_tracker_update, position_tracker) calls activate() first.

1. token.txt (the name stays, whatever the broker) holds 4 lines:
       Broker: DHAN            (DHAN / ANGEL / ZERODHA)
       Client ID: 1100120973
       Name: Ashutosh
       Token: eyJ0eXAi...      (Angel: jwtToken or AUTO; Zerodha: access token)
   Angel / Zerodha keys may be extra lines here too (instead of
   credentials.json): "API Key:", "MPIN:", "TOTP Secret:", "API Secret:".
   Labels may use ":" "-" or "=". A file holding ONLY the token (Cmd+A,
   Cmd+V) also works:
     * Dhan token  -> broker and client ID are read from the token itself.
     * other token -> Broker / Client ID / Name come from the last good run
                      (accounts/.last_session.json -- never holds a token);
                      orders then first ask the broker whose token it is.
2. Safety stops (the script exits, nothing is read or written):
     * no token, unknown broker, client ID not plain letters/digits
     * a Dhan token whose signed-in client ID differs from "Client ID:"
     * "Broker:" says ANGEL/ZERODHA but the token is a Dhan token (or the
       reverse)
3. Files of that account live in
       ~/Desktop/RB_Screener/accounts/<BROKER>_<CLIENT_ID>/
           data/     split.csv, split_backup.csv, orders_log.csv
           reports/  RB_Screener_YYYY-MM-DD.xlsx, RB_Fundamentals_*, tracker_*
           credentials.json   (Angel / Zerodha keys, see broker_api.py)
           account_name.txt   (display name)
   The Name is never part of the path (a typo must not create a new, empty
   account). MARKET data stays shared in ~/Desktop/RB_Screener/data/.
4. Migrations (automatic, once):
     * accounts/<digits>/  ->  accounts/DHAN_<digits>/
     * the very first account ever gets the old global split.csv /
       backups / orders_log.csv / reports moved in (marker accounts/.migrated
       blocks it for every later account).
5. Prints "=== ACTIVE ACCOUNT: DHAN | 1100120973 | Ashutosh ===".

The token is never printed or stored anywhere except token.txt.
"""

import os
import re
import sys
import json
import glob
import shutil
import datetime as dt

import daily_screener as ds
import broker_api as ba

ROOT = ds.HERE                                   # ~/Desktop/RB_Screener
ACCOUNTS = os.path.join(ROOT, "accounts")
MARKER = os.path.join(ACCOUNTS, ".migrated")
LAST = os.path.join(ACCOUNTS, ".last_session.json")
TOKEN_FILE = ds.TOKEN_FILE
_ID_OK = {"DHAN": re.compile(r"^[0-9]{5,15}$"),
          "ANGEL": re.compile(r"^[A-Z0-9]{3,15}$"),
          "ZERODHA": re.compile(r"^[A-Z0-9]{3,15}$")}
_LABELS = (r"broker|client\s*id|client\s*code|user\s*id|bo\s*id|name|"
           r"api\s*key|api\s*secret|mpin|totp\s*secret|totp|access\s*token|token")
_CRED_KEYS = {"api key": "api_key", "api secret": "api_secret", "mpin": "mpin",
              "totp secret": "totp_secret", "totp": "totp_secret"}
BOLD, RED, YEL, END = "\033[1m", "\033[91m", "\033[93m", "\033[0m"

_active = None


class Account(object):
    def __init__(self, broker, cid, token="", name=""):
        self.broker, self.cid, self.token = broker, cid, token
        self.key = "%s_%s" % (broker, cid)
        self.dir = os.path.join(ACCOUNTS, self.key)
        self.data = os.path.join(self.dir, "data")
        self.reports = os.path.join(self.dir, "reports")
        self.split = os.path.join(self.data, "split.csv")
        self.split_backup = os.path.join(self.data, "split_backup.csv")
        self.orders_log = os.path.join(self.data, "orders_log.csv")
        self.name_file = os.path.join(self.dir, "account_name.txt")
        self.creds_file = os.path.join(self.dir, "credentials.json")
        self.expiry = None
        self.token_ok = False
        self.from_cache = False
        self.session = None

    @property
    def name(self):
        """Your own label for this account (display only, never a path)."""
        try:
            txt = open(self.name_file).read().strip().splitlines()[0]
        except (IOError, OSError, IndexError):
            return ""
        return _clean_name(txt)

    @property
    def label(self):
        parts = [self.broker, self.cid] + ([self.name] if self.name else [])
        return " | ".join(parts)


def _clean_name(txt):
    return "".join(c for c in str(txt) if c.isprintable()).strip()[:40]


# ================================================================== file
def read_token_file():
    """token.txt -> {"broker", "client_id", "name", "token"} (strings,
    empty when absent). Never prints anything."""
    out = {"broker": "", "client_id": "", "name": "", "token": "", "creds": {}}
    if not os.path.exists(TOKEN_FILE):
        return out
    lines = [x.strip() for x in open(TOKEN_FILE).read().splitlines()
             if x.strip()]
    plain = []
    for line in lines:
        m = re.match(r"(?i)^(%s)\s*[:=\-]\s*(.*)$" % _LABELS, line)
        if not m:
            plain.append(line)
            continue
        key = " ".join(m.group(1).lower().split())
        val = m.group(2).strip()
        if val in ("", "-") or (val.startswith("[") and val.endswith("]")):
            continue
        if key == "broker":
            out["broker"] = val
        elif key in _CRED_KEYS:            # Angel / Zerodha keys (optional)
            out["creds"][_CRED_KEYS[key]] = val
        elif key.startswith(("client", "user", "bo")):
            out["client_id"] = val.upper()
        elif key == "name":
            out["name"] = _clean_name(val)
        elif not out["token"]:
            out["token"] = val
    if not out["token"] and plain:
        if len(lines) == 1:                   # only the pasted token
            out["token"] = plain.pop(0)
        else:
            jwt = [p for p in plain if ba.looks_like_jwt(p)]
            if jwt:
                out["token"] = jwt[0]
                plain.remove(jwt[0])
    if not out["name"] and plain:             # old 2-line format: token, name
        out["name"] = _clean_name(plain[0])
    return out


def write_token_file(broker, cid, name, token):
    """Rewrite token.txt in the 4-line format (used by zerodha-login)."""
    tmp = TOKEN_FILE + ".tmp"
    with open(tmp, "w") as f:
        f.write("Broker: %s\nClient ID: %s\nName: %s\nToken: %s\n"
                % (broker, cid, name or "-", token))
    os.replace(tmp, TOKEN_FILE)


def _last():
    try:
        d = json.load(open(LAST))
        return d if isinstance(d, dict) else {}
    except (IOError, OSError, ValueError):
        return {}


def _save_last(acc):
    tmp = LAST + ".tmp"
    with open(tmp, "w") as f:                 # no token in here, ever
        json.dump({"broker": acc.broker, "client_id": acc.cid,
                   "name": acc.name,
                   "saved": dt.datetime.now().isoformat(timespec="seconds")},
                  f)
    os.replace(tmp, LAST)


def resolve():
    """(broker, client_id, name, token, from_cache, error)."""
    f = read_token_file()
    tok = f["token"]
    if not os.path.exists(TOKEN_FILE):
        return None, None, "", "", False, "token.txt not found in %s" % ROOT
    if not tok:
        return None, None, "", "", False, "no token found in token.txt"
    broker = ""
    if f["broker"]:
        broker = ba.norm_broker(f["broker"])
        if not broker:
            return None, None, "", "", False, (
                "unknown Broker '%s' (use DHAN, ANGEL or ZERODHA)"
                % f["broker"])
    cid, name, cached = f["client_id"], f["name"], False
    dcid = ba.dhan_client_id(tok)
    if dcid:                                  # a Dhan token: ID is signed in
        if broker and broker != "DHAN":
            return None, None, "", "", False, (
                "Broker says %s but the token is a Dhan token" % broker)
        if cid and cid != dcid:
            return None, None, "", "", False, (
                "'Client ID: %s' does not match the token (%s) -- wrong "
                "account's token" % (cid, dcid))
        broker, cid = "DHAN", dcid
    elif broker == "DHAN":
        return None, None, "", "", False, (
            "not a valid Dhan token (no client ID inside) -- paste the full "
            "token")
    elif not broker and not cid:              # only a token was pasted
        last = _last()
        if not last.get("broker"):
            return None, None, "", "", False, (
                "only a token in token.txt and no earlier session -- "
                "add the Broker / Client ID / Name lines once")
        if last["broker"] == "DHAN":
            return None, None, "", "", False, (
                "last account was DHAN but this is not a Dhan token -- add "
                "the Broker / Client ID lines")
        broker, cid, cached = last["broker"], str(last["client_id"]), True
        name = name or last.get("name", "")
    elif not (broker and cid):
        return None, None, "", "", False, (
            "write BOTH 'Broker:' and 'Client ID:' lines (or only the token)")
    cid = cid.upper()
    if not _ID_OK[broker].match(cid):
        return None, None, "", "", False, (
            "client ID '%s' is not valid for %s -- refusing" % (cid, broker))
    if broker == "ANGEL" and ba.looks_like_jwt(tok):
        who = str(ba.jwt_payload(tok).get("username") or "").upper()
        if who and who != cid:
            return None, None, "", "", False, (
                "Angel token belongs to %s, Client ID says %s" % (who, cid))
    return broker, cid, name, tok, cached, ""


# ================================================================== migration
def _rename_token_file():
    """dhan_token.txt (old name) -> token.txt, once."""
    old = ds.OLD_TOKEN_FILE
    if os.path.exists(old) and not os.path.exists(TOKEN_FILE):
        os.rename(old, TOKEN_FILE)
        print("  renamed: dhan_token.txt -> token.txt (use token.txt from now on)")
    elif os.path.exists(old):
        print("%s  ! dhan_token.txt is ignored -- the scripts read token.txt "
              "(delete the old file)%s" % (YEL, END))


def _rename_old_folders():
    """accounts/<digits>/ (first version) -> accounts/DHAN_<digits>/."""
    done = []
    if not os.path.isdir(ACCOUNTS):
        return done
    for d in sorted(os.listdir(ACCOUNTS)):
        src = os.path.join(ACCOUNTS, d)
        if not (d.isdigit() and os.path.isdir(src)):
            continue
        dst = os.path.join(ACCOUNTS, "DHAN_" + d)
        if os.path.exists(dst):
            print("%s  ! both accounts/%s and accounts/DHAN_%s exist -- not "
                  "merged, move files by hand%s" % (YEL, d, d, END))
            continue
        os.rename(src, dst)
        done.append((d, "DHAN_" + d))
    return done


def _migrate_legacy(acc):
    """Move the old single-account files into the first account's folder."""
    if os.path.exists(MARKER):
        return []
    others = [d for d in os.listdir(ACCOUNTS)
              if d != acc.key and not d.startswith(".")
              and os.path.isdir(os.path.join(ACCOUNTS, d))]
    if others:                       # not the first account -> never migrate
        _mark("skipped: other accounts already exist (%s)" % ", ".join(others))
        return []
    moves = []
    for name in ("split.csv", "split_backup.csv"):
        for src in (os.path.join(ROOT, name), os.path.join(ds.DATA, name)):
            dst = os.path.join(acc.data, name)
            if os.path.exists(src) and not os.path.exists(dst):
                moves.append((src, dst))
    src = os.path.join(ds.DATA, "orders_log.csv")
    if os.path.exists(src) and not os.path.exists(acc.orders_log):
        moves.append((src, acc.orders_log))
    old_reports = os.path.join(ROOT, "reports")
    for pat in ("RB_Screener_*.xlsx", "RB_Fundamentals_*", "tracker_*.csv",
                "swing_*.csv", "investing_*.csv"):
        for src in glob.glob(os.path.join(old_reports, pat)):
            dst = os.path.join(acc.reports, os.path.basename(src))
            if not os.path.exists(dst):
                moves.append((src, dst))
    for src, dst in moves:
        shutil.move(src, dst)
    _mark("migrated %d file(s) into %s" % (len(moves), acc.key))
    return moves


def _mark(text):
    with open(MARKER, "w") as f:
        f.write("%s  %s\n" % (dt.datetime.now().isoformat(timespec="seconds"),
                              text))


# ================================================================== routing
def _mods(name):
    """Loaded copies of a module: imported by name AND/OR run as the script
    (python3 daily_screener.py loads it as __main__, a separate copy)."""
    out = []
    if name in sys.modules:
        out.append(sys.modules[name])
    main = sys.modules.get("__main__")
    f = getattr(main, "__file__", "") or ""
    if os.path.splitext(os.path.basename(f))[0] == name and main not in out:
        out.append(main)
    return out


def _route(acc):
    """Point every loaded module's ACCOUNT paths at this account's folder."""
    for m in _mods("daily_screener"):
        m.REPORTS = acc.reports
    for m in _mods("momentum_screener"):
        m.SPLIT_FILE = acc.split
    for m in _mods("auto_tracker_update"):
        m.SPLIT_FILE, m.BACKUP = acc.split, acc.split_backup
    for m in _mods("position_tracker"):
        m.SPLIT_FILE = acc.split
    for m in _mods("broker_api"):
        m.ORDER_LOG = acc.orders_log
    for m in _mods("fundamentals"):
        m.REPORTS = acc.reports


# ================================================================== activate
def activate(quiet=False):
    """Call first in every live script. Stops the script on any doubt."""
    global _active
    if _active is not None:
        _route(_active)
        return _active
    _rename_token_file()
    broker, cid, name, tok, cached, err = resolve()
    if err:
        print("\n%s%s!!! NO ACTIVE ACCOUNT: %s.%s" % (BOLD, RED, err, END))
        print("    token.txt should hold:  Broker: DHAN / Client ID: ... "
              "/ Name: ... / Token: ...")
        print("    (Every account keeps its own files under "
              "accounts/<BROKER>_<CLIENT_ID>/, so this is required.)")
        sys.exit(1)
    os.makedirs(ACCOUNTS, exist_ok=True)
    renamed = _rename_old_folders()
    acc = Account(broker, cid, tok)
    new = not os.path.isdir(acc.dir)
    for d in (acc.dir, acc.data, acc.reports):
        os.makedirs(d, exist_ok=True)
    if name and name != acc.name:
        set_name(acc, name)                   # remembered even if the line goes
    if broker in ba.CRED_TEMPLATE and not os.path.exists(acc.creds_file) \
            and not read_token_file()["creds"]:
        with open(acc.creds_file, "w") as f:
            json.dump(ba.CRED_TEMPLATE[broker], f, indent=2)
    moves = _migrate_legacy(acc)
    acc.from_cache = cached
    acc.session = ba.Session(broker, tok, cid, acc.creds_file,
                             extra=read_token_file()["creds"])
    acc.expiry = ba.token_expiry(tok)
    acc.token_ok = not (acc.expiry and acc.expiry < ds.now_ist())
    _route(acc)
    _save_last(acc)
    _active = acc
    if not quiet:
        banner(acc)
        for old, newname in renamed:
            print("  renamed: accounts/%s -> accounts/%s" % (old, newname))
        if new:
            print("  new account folder: %s" % acc.dir)
        for src, dst in moves:
            print("  migrated: %s -> accounts/%s/%s" % (
                os.path.relpath(src, ROOT), acc.key,
                os.path.relpath(dst, acc.dir)))
        stray = [p for p in (os.path.join(ROOT, "split.csv"),
                             os.path.join(ds.DATA, "split.csv"))
                 if os.path.exists(p)]
        if stray:
            print("  ! old global file(s) ignored (not this account's): %s"
                  % ", ".join(os.path.relpath(p, ROOT) for p in stray))
        if cached:
            print("%s  (token.txt had only the token -- using %s %s from "
                  "the last run; orders check it with the broker first)%s"
                  % (YEL, broker, cid, END))
        if broker in ba.UNTESTED:
            print("%s  !!! %s support is UNTESTED against the real API -- "
                  "first order: ONE share.%s" % (YEL, ba.LABEL[broker], END))
        if acc.expiry and not acc.token_ok:
            print("%s! Token expired at %s -- paste a fresh one (screens run "
                  "on the free source only).%s"
                  % (RED, acc.expiry.strftime("%d %b %H:%M"), END))
        elif acc.expiry:
            print("  %s token OK, valid till %s" % (
                ba.LABEL[broker], acc.expiry.strftime("%d %b %H:%M")))
    return acc


def set_name(acc, name):
    with open(acc.name_file, "w") as f:
        f.write(_clean_name(name) + "\n")


def banner(acc=None):
    acc = acc or _active
    if acc:
        print("\n%s=== ACTIVE ACCOUNT: %s ===%s" % (BOLD, acc.label, END))
        print("    files: accounts/%s/  (data/, reports/)" % acc.key)
        if not acc.name:
            print("    (to add a name: a 'Name: ...' line in token.txt)")


def _label_of(key):
    b, _, c = key.partition("_")
    a = Account(b, c)
    return a.label


if __name__ == "__main__":
    # python3 account.py                 -> show the active account (+ others)
    # python3 account.py --name "Ashu"   -> set the name for the active account
    a = sys.argv[1:]
    acc = activate(quiet=True)
    if "--name" in a and a.index("--name") + 1 < len(a):
        set_name(acc, a[a.index("--name") + 1])
        print("Name saved for %s." % acc.key)
    banner(acc)
    for d in sorted(os.listdir(ACCOUNTS)):
        if not d.startswith(".") and d != acc.key and \
                os.path.isdir(os.path.join(ACCOUNTS, d)):
            print("    other account: %s" % _label_of(d))
