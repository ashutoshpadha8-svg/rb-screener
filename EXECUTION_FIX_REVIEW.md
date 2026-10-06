# Execution correctness update — 6 October 2026

## What is fixed

This update includes the seven research-engine defects below **and** a separate manual execution safety update in the broker, planner, portfolio, tracker and journal modules. It does not activate a new daily live strategy.

| Defect | Old behavior | Corrected behavior |
|---|---|---|
| Intraday stop funds an earlier open | Stop sale later in a session could finance a BUY at that session's already-past open | OPEN buys precede intraday exits; proceeds cannot travel backwards |
| Intraday target funds an earlier open | Same impossible financing after a target exit | Same causal timeline |
| Entry-day stop ignored | A new open BUY missed the same day's stop touch | New positions receive entry-day protection |
| Entry-day target ignored | A new open BUY missed the same day's target touch | New positions receive entry-day targets |
| Opening target gap overridden | Later low selected a stop even though the existing target executed at the opening gap | Existing decisive opening gaps execute first at actual open |
| Missing open invents a SELL | Prior close substituted as an executable price | Queue the exit until a real open; stale prices only value holdings |
| Long-term loss becomes short-term loss | Concurrent ST and LT losses combined into flexible ST carry | Preserve loss identity; LT losses offset LT gains only |

Additional fix found during daily-mode validation: `buy_delay=1` now locks each sale's proceeds for one session, so a previously scheduled daily BUY cannot spend today's fresh sale proceeds. Delayed candidates refresh against the latest known ranking. Terminal missing closes do not manufacture liquidation. Same-bar stop+target ambiguity uses stop-first after decisive opening gaps; model fills are not proof of order-book fills.

Tax-loss rule reference: [Income Tax Department ITR-2 FAQ](https://www.incometax.gov.in/iec/foportal/help/all-topics/e-filing-services/itr-2-faq). The model remains simplified: current flat rates, no historical rate reconstruction or eight-year carry-expiry tracking. It is not a tax filing calculator.

## Manual execution and per-stock MTF safety update

- Only screener-discovered Buy_Planner shortlist stocks are queried for MTF, once per report run (`rb` / `rbport`). Other holdings, watchlist and SIP names are not independently added to this report refresh. Results are account/broker specific and never reused from yesterday.
- Visible Buy_Planner columns R/S/T: `MTF x (broker)`, `MTF updated IST`, `MTF status (broker)`. Tabular sheets can show the same snapshot for these discovered names; unrelated rows remain empty. Holdings cards show the available rate only for shortlist names. `MTF_Rates` contains only the queried shortlist.
- 4.5x costs position value / 4.5 of own cash. An explicit broker zero is 0x. Failed, missing, malformed or unverified responses are UNKNOWN, not 0 and not a guessed 4x. Both zero and UNKNOWN block MTF. Margin-derived ratios are rounded to two decimals; they are the broker calculator's snapshot, not a promised fill or financing guarantee.
- Fresh broker MTF is checked when computing the selected plan and again after typed YES MTF. A changed/unknown rate stops remaining orders. Final planned Qty is preserved; a new price putting it over the explicit budget blocks submission.
- Literal whole-share BUY/SELL Qty validation: text, negative/fractional values, NaN/Infinity and formulas are errors. Blank SELL means all verified sellable shares; explicit zero means skip. A bad cell can no longer turn into an automatic full sale or auto-sized purchase.
- Report identity must match active broker/client and today's date after Drive pull. Report generation also requires today's master scan and a verified ranking from the completed expected trading session. Rankings have atomic writes plus hash/count manifests; old/partial/missing snapshots cannot become an invented SELL signal. Run rbscan after installing to create the new manifest.
- Fresh broker holdings, product-specific sellable quantity and broker order book are checked before submission and after confirmation. Already-held non-SIP names, pending/current filled manual orders, duplicate selections/SIPs and conflicting BUY+SELL selections block duplicate exposure. A confirmed SELL alone frees a tracked slot.
- Finite fresh cash, an execution buffer and a local remaining-cash reservation protect a multi-order batch; incomplete responses stop the remainder. A read-only price fallback is not accepted for live order sizing. The Rs10000 Cr capitalization floor is checked against dated NSE cap cache (maximum five calendar days); missing/stale/below-floor data blocks BUY.
- Shared account lock covers rbtrack/rbport/rbpos. Intent metadata remains durable before each submission; malformed success/5xx/timeouts are reconciled, never blindly resent. Invalid intent ledgers block orders. --dry-run/--no-orders do not invent LIVE fills or mutate trade selections/settings/positions as if an order executed.
- Dhan availableQty=0 is respected; Angel DELIVERY versus MARGIN/MTF and Kite nested MTF quantities remain separate for sale checks. Unknown/ambiguous quantities fail closed. MTF positions can be read from positions as well as demat holdings. Angel after-hours orders use NORMAL variety as documented.
- LIMIT prices use each broker instrument's tick (Dhan/Angel paise converted to rupees; Kite rupees), not a universal 0.05. Missing tick blocks LIMIT submission. MARKET orders retain their existing behavior and have no fill-price ceiling; a next-open gap can exceed estimated cash/margin. Broker acceptance is not proof of a completed fill.
- Journal only counts confirmed filled BUY quantity; partial SELL reconciliation preserves the remaining lot and does not reuse the first sale's price for later sales. Journal history can be incomplete for external trades outside retained broker history; broker statements remain the authority.

Regression logs: reports/verification. Spreadsheet evidence: five MTF scenarios, **1910 formulas**, recalculated using LibreOffice, zero Excel error cells and quantity/own-cash parity with Python. The preview uses DEMO symbols and simulated broker values; no current account margin is asserted.

Official API references: [Dhan portfolio/positions](https://dhanhq.co/docs/v2/portfolio/), [SmartAPI](https://smartapi.angelone.in/docs), [Kite holdings/MTF](https://kite.trade/docs/connect/v3/portfolio/), [Dhan tick-size units](https://dhan.co/support/platforms/dhanhq-api/in-what-unit-is-the-tick-size-provided-in-the-scrip-master/).

## User's daily strategy specification

- Check BUY and SELL daily; use completed prior-close ranks and next-session execution in research.
- BUY only raw ranks 1–5. Keep old positions through rank 40; SELL at rank 41 or when no longer eligible.
- No duplicate top-up of already held stocks, no new capital, and skip unfunded buys.
- A signal requires the user's acceptance. There is no automatic real order in this update.
- Every prospective BUY needs capitalization at least Rs 10,000 crore. Historical tests can enforce only a constant-share estimated cap, not independently verified historical cap.
- Existing risk comparison uses at most four Momentum positions per sector. Also report an unrestricted-sector diagnostic. Do not promote rank 6 when a Top-5 name is blocked.
- No fixed five-stock ceiling: cash determines additions. `N=20` here sizes each purchase, while `max_positions=0` removes an extra count ceiling; `buffer=2` retains rank <=40.
- NAV/20 and initial-capital/20 are separate sizing assumptions. NAV/5 and initial-capital/5 are concentration diagnostics, not automatically selected live settings.
- The earlier 60/25/15 preference concerns amounts in the stocks the user manually selects. This raw Top-5 research does not impose a class quota or substitute worse ranks.

Existing recommendation policy remains unchanged; live safety checks and the MTF display are updated. TRADING stays under user control and typed confirmations remain mandatory. Account files and actual holdings are not edited by this patch. Daily Top-5 is a research/preview specification here, not a silently activated live strategy. Integrating that opt-in live profile needs a separate concrete UI/code approval after reviewing the preview.

## Verification and reproduction

Run `python3 tests/run_offline.py`. Each regression file runs in a separate process with external sockets blocked. All eleven groups pass, **240 checks**, including 27 timeline/rank/funding/tax checks, 17 literal-input/manual-flow tests and 26 additional MTF/execution-safety tests. One randomized test also covers 30 paths. The existing optional pycel formula comparison is skipped when pycel is absent; delivered Excel reports are separately recalculated with LibreOffice and their cached formulas checked.

Offline historical test (requires an existing public-price cache):

```bash
python3 daily_top5_hold40_study.py --data ./data --out ./reports/daily_hold40
```

Research tester can also express the accumulation rule, but its regular loader may download history:

```bash
python3 strategy_tester.py --slots 20 --freq D --exit-freq D --keep 40 --buy-top 5 --max-positions 0 --mix none --allocation nav --no-live
```

Set `--buy-delay 1` for delayed sale-proceeds availability. Tester retains its legacy 6% idle-cash convention; the offline daily study assumes **0% idle cash interest**, explicitly. These two commands therefore need not give identical results.

## Limits

Passing synthetic tests cannot guarantee bug-free software or profitable trades. All pre-update SL/target studies must be rerun with the corrected engine. Daily hold40 returns still depend on survivors-only data, historical-cap estimation, missing sessions and unverified corporate actions. The study records actual exposure across STAR (6 Dec 2024) and VEDL (30 Apr 2026) demergers; raw price changes omit distributed shares/entitlements. Do not report these outputs as validated economic returns or a forecast of the next twelve months.

Sources: [NSE STAR demerger reference](https://nsearchives.nseindia.com/web/sites/default/files/2025-02/ind_prs05022025_1_0.pdf), [NSE VEDL special pre-open circular](https://nsearchives.nseindia.com/content/circulars/CMTR73856.pdf).

Personal portfolio data and account identifiers must stay out of GitHub. The local portfolio preview is a separate private artifact. Use only explicit code/tests/sanitized research paths when committing.
