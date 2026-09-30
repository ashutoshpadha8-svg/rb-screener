# Steps 1–3 completed — 30 September 2026

The workspace copy has the execution recovery, delayed fill-price reconciliation, shared sizing and funded-tax changes below. Step 4 (a new 1–2 week strategy) is unchanged. Validation used fake brokers, temporary/in-memory account ledgers and existing historical price files. No real order was sent and no trading switch or account configuration was changed.

## 1. Recovered BUYs reach the position ledger

- Before sending a BUY, `order_intents.csv` now stores the complete planned position: strategy, allocation leg, requested quantity, entry reference and SIP metadata where applicable.
- `rbtrack` restores a missing position by tag/order ID before planning new trades. The recovered position is written to `split.csv` before the intent is marked `position_saved=1`.
- Crashes before the broker reply, before the split write, and after the split write but before the marker are covered. Repeated recovery matches the existing order ID and does not append another position or submit another order.
- Untracked BUYs reserve momentum slots and industry capacity. An old completed or cancelled partially filled BUY stays blocked until its actual position is recorded. A pending SELL keeps occupying its slot.
- SIP recovery can retry its log write; the SIP log deduplicates broker order IDs. A position already recorded and subsequently sold is not resurrected.
- Split and intent writes use a flushed temporary file followed by atomic replacement.

**Older intents:** existing split rows are recognized by order ID. An older missing-position intent without the new strategy metadata cannot be reconstructed reliably. It remains blocked/reserved and prints a review message. This migration deliberately requires checking that order and its strategy manually; it never treats missing metadata as proof that no order happened. Do not mark a filled order `not-placed` to clear the warning.

## 2. Final quantity and final price are reconciled separately

- The confirmed cumulative quantity never decreases because an order/trade book temporarily reports fewer fills.
- A terminal order with a fill but no cumulative average keeps its actual shares and `fill price pending`; later `rbtrack --sync` queries it again.
- The price is linked to the quantity it prices. An average for the first 3 shares cannot silently become the price of a later 6-share fill.
- The Dhan adapter now also handles a lagging trade book: order quantity 6 plus trade-book average for only 3 returns quantity 6 with price pending, unless the order itself supplies the full cumulative average.
- Once the full average arrives, split quantity/price and the existing journal synchronization use the corrected cost basis and fees. Partial cancelled fills stay held; only confirmed zero-fill cancellations become zero-share rows.

New split tracking columns: `intent_tag`, `ordered_qty`, `filled_qty_confirmed`, `fill_avg_price`, `fill_avg_qty`, `price_pending`. New intent columns are added when reading older ledgers; personal files were not migrated during this audit.

## 3. Sizing is explicit and research tax is funded

`position_sizing.py` supplies the shared slot budget and whole-share calculation used by the live planner, momentum quantity previews, production rank backtest and execution-delay study.

- **Live default:** configured starting capital divided by slots. With Rs 200,000 and 20 slots, a new position gets a fixed Rs 10,000 reference budget. Existing manual Amount overrides are preserved.
- **NAV/20:** an explicit research allocation; it is not automatically activated for live accounts.
- **Research buying power:** available cash minus accrued tax under the existing TaxBook model. Whole shares include the modeled buy cost and slippage, and annual tax settlement cannot borrow implicit cash.
- `TaxBook.due()` previews the existing model on a copy; it does not settle or change loss carry-forwards.

The live AMO is sized from the available pre-order quote; the backtest uses its modeled fill-day open and transaction costs. Sharing the budget rule does not reproduce every real broker fill, funding restriction or manual Amount override. This patch does not automatically reserve tax in a live broker account or redesign tax law.

## Validation

| Suite | Result |
|---|---:|
| Supplied execution checks, including tracked-position completion | 37 / 37 |
| Original independent expectations (unchanged) | 6 / 6 |
| Follow-up expectations (unchanged) | 3 / 3 |
| New recovery / price / sizing / tax unittest cases | 24 / 24 |

All four commands exited successfully. The supplied test was updated to reflect the correct requirement: an old completed BUY is released only after its position has been recorded. Its separate Dhan fixture resets tracking fields when changing to a new order ID. Neither independent review script's expectations were weakened.

The 64-row offline study covers two universes, two sizing modes, four execution scenarios, three time periods, plus eight zero-interest and eight no-tax controls. All 64 rows have **zero negative-cash days, at most 20 positions and at most four positions per known industry**. Twelve same-open comparisons match the production `strategy_lab.run_rank` equity curve within Rs 0.00001; maximum difference was Rs 0.000000002794. Eight no-tax controls reproduce the earlier study's final wealth.

## Funded backtest results

Full period: 1 January 2013–25 September 2026. Start capital Rs 200,000. These figures include the existing standardized model tax, transaction costs and **assumed 6% cash interest**. The older NAV outputs with unfunded tax are superseded for this comparison.

| Universe | Sizing | Same-open CAGR | +1 session, refreshed CAGR | Same-open max DD | +1 session max DD |
|---|---|---:|---:|---:|---:|
| Estimated historical Rs 10k Cr | Fixed Rs 10,000 | 14.12% | 14.10% | -19.07% | -18.56% |
| Estimated historical Rs 10k Cr | NAV/20 research | 23.34% | 22.77% | -36.06% | -35.81% |
| Current Rs 10k Cr survivors | Fixed Rs 10,000 | 16.16% | 15.80% | -19.18% | -18.26% |
| Current Rs 10k Cr survivors | NAV/20 research | 30.10% | 29.88% | -37.17% | -36.80% |

The one-session delay represents replacement buys waiting for a SELL confirmation; ranks are refreshed using the latest prior close. Already vacant slots do not need to wait. The study assumes full SELL fills and does not replay broker events.

**The +1-session advantage is not robust.** Under 6% cash interest the estimated-universe NAV result falls from 23.34% to 22.77%. With cash interest set to zero, these values are 22.43% and 22.51%; fixed sizing gives 12.57% and 12.66%. Reserving tax changes which trades can be funded, so the updated NAV results are not merely the earlier return minus a tax adjustment. Do not choose a delay solely because one historical variant returned more.

Data still has survivorship bias: 535 histories were loaded out of 1,515 requested; 525 belong to the current Rs 10k Cr survivor set. Historical market cap uses present share counts; current industries are applied historically. Benchmark/most price files end 25 September, nine stock files end 18 September, and market caps are dated 29 September. Dividends, circuit locks, partial fills, rejects and unsettled-funds constraints are not modeled. Tax is the existing standardized model, not year-by-year historical law. This rerun is neither fresh out-of-sample proof nor a newly validated 1–2 week strategy.

## Files

- `RB_Funded_Backtest_2026-09-30.xlsx`: Read first, full-period comparison, zero-interest comparison, all 64 results, annual returns, monthly equity and two equity charts. No order-action sheets.
- `backtest/summary.csv`: all 64 numeric results.
- `backtest/paired_delay_effect.csv`: matched effects of each execution delay.
- `backtest/*_fills.csv` and `*_trades.csv`: modeled trade detail for all 16 full-period variants.
- `backtest/metadata.json` and `experiment_spec.json`: original run hashes, data dates and assumptions.
- `PACKAGE_PROVENANCE.json`: packaged code hashes, test counts and the execution-only change made after the backtest finished.
- `execution_sizing_tax.patch`: reviewable source diff; `before/` in the workspace retains the earlier source files.
- `INSTALL.md`: backup, install and mock verification commands for the separate home-folder installation.

Only `/Users/ashutoshpadha/Downloads/codex/RB_Screener` was edited. The separate `~/RB_Screener` installation must receive the update before these fixes apply there.
