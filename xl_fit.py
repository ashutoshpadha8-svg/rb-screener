"""
xl_fit.py -- make table columns fit their content (30 Sep 2026, RB: "fit karo
columns ko ache se, sab jagah").

fit_sheet(ws): finds the header row (first row in 1..8 with >= 3 bold text
cells), sets every column's width from its header words and its values
(numbers measured as shown), header row tall enough for its wrapped words,
body cells on one line (no tall rows, wrap off, saved heights cleared). Long note lines (> 60 chars) and
cells under the table are ignored, so notes never blow up a column.
fit_workbook(wb, skip=...) runs it on every sheet except the skipped ones
(Dashboard / Holdings cards have their own layout).
"""

import datetime as dt
import math

from openpyxl.styles import Alignment
from openpyxl.utils import get_column_letter as L

MIN_W, MAX_W, NOTE_LEN = 6, 45, 60


def _shown(v, fmt):
    """Length of the value as Excel / Sheets shows it."""
    if v is None:
        return 0
    if isinstance(v, bool):
        return 5
    if isinstance(v, (dt.date, dt.datetime)):
        return 10
    if isinstance(v, (int, float)):
        fmt = fmt or "General"
        x = float(v)
        if "%" in fmt:
            return len("%.1f%%" % (x * 100))
        if "#,##0" in fmt:
            dec = 1 if ".0" in fmt else 0
            return len(format(x, ",.%df" % dec))
        if isinstance(v, int) or x.is_integer():
            return len(str(int(x)))
        return len("%.2f" % x)
    s = str(v)
    if s.startswith("="):
        return 10                     # formula: ~ a number
    return max(len(p) for p in s.split("\n")) if s else 0


def header_row(ws, max_row=8):
    for r in range(1, min(ws.max_row, max_row) + 1):
        n = 0
        for c in range(1, ws.max_column + 1):
            cell = ws.cell(row=r, column=c)
            fill = cell.fill is not None and cell.fill.fill_type == "solid"
            if isinstance(cell.value, str) and cell.value.strip() and \
                    ((cell.font is not None and cell.font.b) or fill):
                n += 1
        if n >= 3:
            return r
    return None


def fit_sheet(ws):
    h = header_row(ws)
    if not h:
        return False
    ncol = max(c for c in range(1, ws.max_column + 1)
               if ws.cell(row=h, column=c).value not in (None, "")) \
        if ws.max_column else 0
    last = h
    while last + 1 <= ws.max_row and \
            ws.cell(row=last + 1, column=1).value not in (None, ""):
        last += 1
    lines = 1
    for c in range(1, ncol + 1):
        head = str(ws.cell(row=h, column=c).value or "")
        word = max([len(w) for w in head.split()] or [0])
        data, sizes = 0, []
        for r in range(h + 1, last + 1):
            cell = ws.cell(row=r, column=c)
            n = _shown(cell.value, cell.number_format)
            sizes.append((cell, n))
            data = max(data, n if n <= NOTE_LEN else MAX_W)
        half = math.ceil(len(head) / 2)          # header in <= 2 lines
        w = min(MAX_W, max(MIN_W, word + 3, half + 3, data + 2))
        for cell, n in sizes:         # table rows stay ONE line high (RB:
            al = cell.alignment       # tall rows = bad); long text is cut,
            if al is not None and al.wrap_text:   # full text on click
                cell.alignment = Alignment(horizontal=al.horizontal,
                                           vertical=al.vertical,
                                           wrap_text=False)
        ws.column_dimensions[L(c)].width = w
        lines = max(lines, math.ceil((len(head) + 1) / max(w - 1, 1)))
    ws.row_dimensions[h].height = 15 * min(lines, 4) + 4
    for r in range(h + 1, last + 1):  # old saved heights would keep rows tall
        if r in ws.row_dimensions:
            ws.row_dimensions[r].height = None
    return True


def fit_workbook(wb, skip=("Dashboard", "Holdings")):
    for ws in wb.worksheets:
        if ws.title in skip or ws.sheet_state != "visible":
            continue
        try:
            fit_sheet(ws)
        except Exception:
            pass                      # layout only -- never stop a report


def check():
    """python3 xl_fit.py check -> what today's master file really contains
    (no prices, no token): newest scan, Momentum_Top20 columns + widths,
    and whether the Google Drive copy is as new as the local file."""
    import glob
    import os
    from openpyxl import load_workbook
    here = os.path.dirname(os.path.abspath(__file__))
    files = [f for f in glob.glob(os.path.join(here, "reports",
                                               "RB_Screener_*.xlsx"))
             if not os.path.basename(f).startswith("~$")]
    if not files:
        print("No master scan in reports/.")
        return
    f = max(files, key=os.path.getmtime)
    print("Newest master: %s  (saved %s)" % (os.path.basename(f), dt.datetime
          .fromtimestamp(os.path.getmtime(f)).strftime("%d %b %H:%M")))
    wb = load_workbook(f)
    for n in ("Momentum_Top20", "Swing"):
        if n not in wb.sheetnames:
            print("  %s: MISSING" % n)
            continue
        ws = wb[n]
        heads = [ws.cell(row=1, column=c).value for c in range(1, 6)]
        widths = [ws.column_dimensions[L(c)].width for c in range(1, 6)]
        print("  %s: %s | widths %s | header height %s"
              % (n, heads, widths, ws.row_dimensions[1].height))
    print("  Signal_Tracker tab: %s" % ("yes" if "Signal_Tracker" in
                                         wb.sheetnames else "NO"))
    try:
        import drive_copy
        dst = drive_copy._target(f)
        if dst and os.path.exists(dst):
            late = os.path.getmtime(f) - os.path.getmtime(dst)
            print("  Drive copy: %s" % ("same as local" if late < 5 else
                                        "OLDER than local by %d min"
                                        % (late // 60)))
        else:
            print("  Drive copy: not found")
    except Exception as e:
        print("  Drive copy: could not check (%s)" % type(e).__name__)
    for m in ("momentum_screener", "signal_tracker", "portfolio",
              "daily_screener", "xl_fit"):
        p = os.path.join(here, m + ".py")
        print("  %-18s %s bytes" % (m + ".py", os.path.getsize(p)
                                    if os.path.exists(p) else "MISSING"))


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["check"]:
        check()
    else:
        print("usage: python3 xl_fit.py check")
