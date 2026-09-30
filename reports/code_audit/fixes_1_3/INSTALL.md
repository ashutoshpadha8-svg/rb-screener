# Install steps 1–3

The updated code is already in the Codex workspace. The ZIP is an overlay containing the nine changed/new Python files, regression tests and offline reports. It contains no credentials, account data, settings, holdings or price cache. It does not activate trading or place orders.

Close running `rb` / `rbtrack` processes first. For the separate home-folder installation, run these commands in Terminal. Check the ZIP from its folder:

```bash
cd /Users/ashutoshpadha/Downloads/codex
shasum -a 256 -c RB_Screener_FIXES_1_3_2026-09-30.sha256
```

Back up the existing installation before applying the overlay. This backup includes personal files and must stay private:

```bash
ditto ~/RB_Screener ~/RB_Screener_before_fixes_1_3_$(date +%Y%m%d_%H%M%S)
unzip -o /Users/ashutoshpadha/Downloads/codex/RB_Screener_FIXES_1_3_2026-09-30.zip -d ~/RB_Screener
```

Run the mock suites; none needs a token or sends a real order:

```bash
cd ~/RB_Screener
python3 tests/test_execution.py
python3 reports/code_audit/test_execution_independent_review.py
python3 reports/code_audit/test_execution_followup_review.py
python3 tests/test_recovery_tax.py
```

Expected results: `37 / 37 passed`, `6/6`, `3/3`, and `Ran 24 tests ... OK` respectively. Existing dependencies for this project are required; no new external runtime package is needed by the execution changes.

If an older BUY intent is missing its position and has no recovery metadata, the script keeps it blocked/reserved and prints a warning. Check its actual broker order and strategy before repairing that historical position. Do not use `not-placed` for a filled order.

Optional offline backtest reproduction, using the installation's existing historical price/market-cap/industry cache:

```bash
cd ~/RB_Screener
python3 reports/code_audit/fixes_1_3/reproduce_backtest.py
python3 reports/code_audit/fixes_1_3/build_report.py
```

These commands write research outputs, not orders. The reproduced numbers depend on the cache snapshot. The report builder needs the project's existing `openpyxl` package. Production account permissions, broker switches and live deployment remain separate from the mock tests.
