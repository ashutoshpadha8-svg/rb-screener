#!/usr/bin/env python3
"""
ACCOUNT ISOLATION  --  one folder per Dhan client
=================================================

Every live script (daily_screener, momentum_screener, fundamentals,
auto_tracker_update, position_tracker) calls activate() first:

  1. Reads ~/Desktop/RB_Screener/dhan_token.txt and takes the Dhan client ID
     from the token's payload (the same JWT decode the screener already uses).
     No token / unreadable / not a plain number -> the script STOPS.
     dhan_token.txt may also hold "Client ID: ..." (must match the token,
     else STOP) and "Name: ..." lines (or a plain 2nd line = name); the name is
     saved in accounts/<ID>/account_name.txt, so it stays after you paste
     a new token over the whole file.
     (Digits only, so a strange token can never point the path elsewhere.)
  2. Routes all ACCOUNT files to
        ~/Desktop/RB_Screener/accounts/<CLIENT_ID>/
            data/     split.csv, split_backup.csv, orders_log.csv
            reports/  RB_Screener_YYYY-MM-DD.xlsx, RB_Fundamentals_*, tracker_*.csv
     by re-pointing the path constants of the modules that are loaded.
     MARKET data stays shared in ~/Desktop/RB_Screener/data/ (price history,
     NSE files, scrip master, Screener pages, momentum ranking) -- it is the
     same for every account and is 500+ MB.
  3. One-time migration: the FIRST account ever activated (no other folder in
     accounts/, no marker file) gets the old global split.csv / backups /
     orders_log.csv / RB_Screener reports MOVED into its folder. After that a
     marker file (accounts/.migrated) blocks any further migration, so a
     second account can never pick up the first account's positions.
  4. Prints a bold "=== ACTIVE ACCOUNT: <CLIENT_ID> ===" header.

The token is never printed. Its signature is not verified locally (only
Dhan can); a forged token would give a folder name but Dhan rejects it.
"""

import os
import re
import sys
import glob
import shutil
import datetime as dt

import daily_screener as ds

ROOT = ds.HERE                                   # ~/Desktop/RB_Screener
ACCOUNTS = os.path.join(ROOT, "accounts")
MARKER = os.path.join(ACCOUNTS, ".migrated")
_ID_OK = re.compile(r"^[0-9]{5,15}$")

_active = None


class Account(object):
    def __init__(self, cid):
        self.cid = cid
        self.dir = os.path.join(ACCOUNTS, cid)
        self.data = os.path.join(self.dir, "data")
        self.reports = os.path.join(self.dir, "reports")
        self.split = os.path.join(self.data, "split.csv")
        self.split_backup = os.path.join(self.data, "split_backup.csv")
        self.orders_log = os.path.join(self.data, "orders_log.csv")
        self.name_file = os.path.join(self.dir, "account_name.txt")

    @property
    def name(self):
        """Your own label for this account (display only, never a path)."""
        try:
            txt = open(self.name_file).read().strip().splitlines()[0]
        except (IOError, OSError, IndexError):
            return ""
        return "".join(c for c in txt if c.isprintable())[:40]

    @property
    def label(self):
        return "%s (%s)" % (self.cid, self.name) if self.name else self.cid


def client_id_from_token():
    """(client_id, error). Never returns or prints the token itself."""
    if not os.path.exists(ds.TOKEN_FILE):
        return None, "dhan_token.txt not found in %s" % ROOT
    tok = ds.read_token()
    if not tok:
        return None, "no token found in dhan_token.txt"
    cid, exp = ds.token_info(tok)
    if not cid:
        return None, "could not read a client ID from the token (paste the full token)"
    if not _ID_OK.match(cid):
        return None, "client ID in the token is not a plain number -- refusing"
    written = ds.read_token_file()[2]
    if written and written != cid:
        return None, ("'Client ID: %s' in dhan_token.txt does not match the "
                      "token (%s) -- wrong account's token" % (written, cid))
    return cid, ""


def _migrate(acc):
    """Move the old single-account files into the first account's folder."""
    if os.path.exists(MARKER):
        return []
    others = [d for d in os.listdir(ACCOUNTS)
              if d != acc.cid and not d.startswith(".")
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
    _mark("migrated %d file(s) into %s" % (len(moves), acc.cid))
    return moves


def _mark(text):
    with open(MARKER, "w") as f:
        f.write("%s  %s\n" % (dt.datetime.now().isoformat(timespec="seconds"),
                              text))


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
    """Point every loaded module's ACCOUNT paths at this client's folder."""
    for m in _mods("daily_screener"):
        m.REPORTS = acc.reports
        m.CLIENT_ID = acc.cid
    for m in _mods("momentum_screener"):
        m.SPLIT_FILE = acc.split
    for m in _mods("auto_tracker_update"):
        m.SPLIT_FILE, m.BACKUP = acc.split, acc.split_backup
    for m in _mods("position_tracker"):
        m.SPLIT_FILE = acc.split
        m.CLIENT_ID = acc.cid
    for m in _mods("dhan_orders"):
        m.ORDER_LOG = acc.orders_log
    for m in _mods("fundamentals"):
        m.REPORTS = acc.reports


def activate(quiet=False):
    """Call first in every live script. Stops the script if no valid token."""
    global _active
    if _active is not None:
        _route(_active)
        return _active
    cid, err = client_id_from_token()
    if not cid:
        print("\n\033[1m\033[91m!!! NO ACTIVE ACCOUNT: %s.\033[0m" % err)
        print("    Paste today's Dhan token into dhan_token.txt and run again.")
        print("    (Every account keeps its own files under accounts/<CLIENT_ID>/"
              ", so a token is required.)")
        sys.exit(1)
    acc = Account(cid)
    new = not os.path.isdir(acc.dir)
    for d in (ACCOUNTS, acc.dir, acc.data, acc.reports):
        os.makedirs(d, exist_ok=True)
    name = ds.read_token_file()[1]          # optional 2nd line of the file
    if name and name != acc.name:
        set_name(acc, name)                 # remembered even if the line goes
    moves = _migrate(acc)
    _route(acc)
    _active = acc
    if not quiet:
        banner(acc)
        if new:
            print("  new account folder: %s" % acc.dir)
        for src, dst in moves:
            print("  migrated: %s -> accounts/%s/%s" % (
                os.path.relpath(src, ROOT), cid, os.path.relpath(dst, acc.dir)))
        stray = [p for p in (os.path.join(ROOT, "split.csv"),
                             os.path.join(ds.DATA, "split.csv"))
                 if os.path.exists(p)]
        if stray:
            print("  ! old global file(s) ignored (not this account's): %s"
                  % ", ".join(os.path.relpath(p, ROOT) for p in stray))
    return acc


def set_name(acc, name):
    with open(acc.name_file, "w") as f:
        f.write(name.strip() + "\n")


def banner(acc=None):
    acc = acc or _active
    if acc:
        print("\n\033[1m=== ACTIVE ACCOUNT: %s ===\033[0m" % acc.label)
        print("    files: accounts/%s/  (data/, reports/)" % acc.cid)
        if not acc.name:
            print("    (to add a name: a 'Name: ...' line in dhan_token.txt)")


if __name__ == "__main__":
    # python3 account.py                 -> show the active account
    # python3 account.py --name "Ashu"   -> set the name for the token's account
    a = sys.argv[1:]
    acc = activate(quiet=True)
    if "--name" in a and a.index("--name") + 1 < len(a):
        set_name(acc, a[a.index("--name") + 1])
        print("Name saved for %s." % acc.cid)
    banner(acc)
    others = sorted(d for d in os.listdir(ACCOUNTS)
                    if not d.startswith(".") and d != acc.cid)
    for d in others:
        print("    other account: %s" % Account(d).label)
