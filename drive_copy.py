#!/usr/bin/env python3
"""
DRIVE COPY  --  your output files in Google Drive, sorted, editable in Google Sheets
===================================================================================

Needs NO Google login / API: it only copies files into the Google Drive for
desktop folder on this Mac (~/Library/CloudStorage/GoogleDrive-<you>/My Drive).
The Drive app uploads them; open them on drive.google.com -> Google Sheets
edits the .xlsx directly.

  My Drive/RB_Reports/
    Master_Scan/2026-09/RB_Screener_2026-09-27.xlsx       <- rbscan
    DHAN_Ashutosh/Portfolio_DHAN_Ashutosh.xlsx   <- rb (one file, updated daily)
    DHAN_Ashutosh/Watchlist_DHAN_Ashutosh.txt
    ANGEL_tanu_Angel/...

ONLY these report files are ever copied. token.txt, credentials.json, keys,
split.csv and data/ never leave ~/RB_Screener.

Picks you make in Google Sheets (Buy_Planner: Pick / Qty / budget) come back:
rbport and rbtrack first check if the Drive copy was edited after it was
copied there, and if so take it over the local file (local copy saved as
data/_drive_backup/).

  python3 drive_copy.py        -> shows where the folder is (or why it is off)
"""

import os
import re
import sys
import glob
import json
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "data", "_drive_copy.json")
TOP = "RB_Reports"


def drive_root():
    """My Drive folder of Google Drive for desktop, or None."""
    env = os.environ.get("RB_DRIVE_ROOT")
    if env:
        return env if os.path.isdir(env) else None
    for base in sorted(glob.glob(os.path.expanduser(
            "~/Library/CloudStorage/GoogleDrive-*"))):
        for name in ("My Drive", "Meine Ablage", "Mi unidad"):
            p = os.path.join(base, name)
            if os.path.isdir(p):
                return p
    return None


def _where(local):
    """Drive sub-folder for a report file, or None (never copy anything else)."""
    name = os.path.basename(local)
    m = re.match(r"RB_Screener_(\d{4}-\d{2})-\d{2}.*\.xlsx$", name)
    if m:
        return os.path.join("Master_Scan", m.group(1))
    m = re.match(r"Portfolio_(?:(.+)_)?(\d{4}-\d{2})-\d{2}.*\.xlsx$", name)
    if m:                                   # old one-file-per-day names
        return os.path.join(m.group(1) or "account", m.group(2))
    m = re.match(r"Portfolio_(.+)\.xlsx$", name)
    if m:                                   # the one file per account
        return m.group(1)
    m = re.match(r"Watchlist_(.+)\.txt$", name)
    if m:
        return m.group(1)
    return None


def _target(local):
    root, sub = drive_root(), _where(local)
    if not root or not sub:
        return None
    return os.path.join(root, TOP, sub, os.path.basename(local))


def _state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except (IOError, OSError, ValueError):
        return {}


def _save_state(st):
    try:
        with open(STATE, "w") as f:
            json.dump(st, f, indent=0)
    except (IOError, OSError):
        pass


def push(local, quiet=False):
    """Copy a report into My Drive/RB_Reports/... Returns the Drive path."""
    dst = _target(local)
    if not dst or not os.path.exists(local):
        return None
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(local, dst)
        st = _state()
        st[dst] = os.path.getmtime(dst)       # our copy time -> later edits
        _save_state(st)
        if not quiet:
            print("  Google Drive copy: My Drive/%s"
                  % os.path.relpath(dst, drive_root()))
        return dst
    except (IOError, OSError) as e:
        if not quiet:
            print("  ! Google Drive copy failed (%s) -- local file is fine."
                  % type(e).__name__)
        return None


def pull(local, quiet=False):
    """If the Drive copy was edited (Google Sheets) after we copied it,
    take it over the local file. Returns True when the local file changed."""
    dst = _target(local)
    if not dst or not os.path.exists(dst):
        return False
    try:
        copied = _state().get(dst)
        if copied is None or os.path.getmtime(dst) <= copied + 2:
            return False
        if os.path.exists(local):            # safety copy, out of sight
            bdir = os.path.join(HERE, "data", "_drive_backup")
            os.makedirs(bdir, exist_ok=True)
            shutil.copyfile(local, os.path.join(bdir, os.path.basename(local)))
        shutil.copyfile(dst, local)
        st = _state()
        st[dst] = os.path.getmtime(dst)
        _save_state(st)
        if not quiet:
            print("  took your Google Sheets edits: %s"
                  % os.path.basename(local))
        return True
    except (IOError, OSError) as e:
        if not quiet:
            print("  ! could not read the Google Drive copy (%s) -- using the "
                  "local file." % type(e).__name__)
        return False


if __name__ == "__main__":
    r = drive_root()
    if r:
        print("Google Drive copy ON -> %s" % os.path.join(r, TOP))
    else:
        print("Google Drive copy OFF: no Google Drive for desktop folder "
              "(~/Library/CloudStorage/GoogleDrive-*/My Drive) found.")
    sys.exit(0)
