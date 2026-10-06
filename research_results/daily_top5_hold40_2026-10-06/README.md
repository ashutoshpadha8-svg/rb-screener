# Daily Top-5 additions / rank >40 exits — exploratory outputs

The daily research starts with Rs200,000 cash, assumes acceptance of every eligible prior-close signal and next-open execution, uses whole shares and modeled Dhan delivery costs, and adds no money. NAV/20 is the main sizing assumption; there is no extra five-stock holding ceiling. Old holdings remain through rank40. Idle cash earns 0%. Raw Top5 ranks are not altered to force market-cap class quotas.

These numbers are NOT validated economic returns or forecasts. Current survivors and price-scaled current cap estimates are not true historical membership. STAR and VEDL were held across demergers; distributed entitlements are missing from raw price returns. One-price bars may not fill. Flat modeled current tax rates are not historical tax reconstruction. Tax reserves can change selection/timing, so modeled-tax results use different portfolio paths from before-tax results and can occasionally outperform them; this is not a tax benefit claim.

`summary.csv` and `rolling12.csv` report overlapping complete-month rolling12 windows. The partial ending September2026 is excluded. The primary NAV/20 modeled-tax row has mean21.4%, median13.05%, worst12m -17.26%, and drawdown -32.41%; it remains an unvalidated proxy. Fixed initial Rs10000 buys give mean11.82%. Median closed-trade holding is110 calendar days, not a promised short-term turnaround. See `metadata.json` for known exposures, costs, data gaps and assumptions.

Default loader explicitly omits a globally missing stock session, 11 May2022, from indicators and execution. Retaining it with `--keep-global-gaps` gives a different diagnostic (mean20.83% after modeled tax); missing data must not be mistaken for a genuine market-wide rank liquidation.

Run `python3 daily_top5_hold40_study.py --data ./data --out ./reports/daily_hold40` with an existing cache. No credentials, broker imports, account activation, downloads or real orders are used. Changes do not enable a daily live strategy; review the local Portfolio preview and `EXECUTION_FIX_REVIEW.md` first. Personal account workbooks are deliberately excluded from GitHub.
