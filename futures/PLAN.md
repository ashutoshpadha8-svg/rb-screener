# Futures Prop Bot — Plan (started 27 Sep 2026)

Fresh project, separate from the NSE swing screener. Nothing from the swing system carries over.

## Fixed decisions
- Firm: Topstep (EOD trailing drawdown, official ProjectX API allows bots in Combine + Express).
- Apex is out: its rules ban AI/bots/algos on all account types.
- Instruments: micros only (MES $5/pt, MNQ $2/pt). Full ES = $50/pt is too big for a $2,000 drawdown.
- Payout: bank wire / Rise only. No crypto.

## Topstep API rules (verify before going live)
- ProjectX API: $29/mo ($14.50 with code "topstep"). REST + WebSocket, works from Python.
- Allowed: Combine, Express Funded. NOT allowed: Live Funded via API.
- Orders must come from own device (Mac Mini). VPS / VPN / remote server = banned.
- No HFT. No sandbox - test on Practice account.
- Get written confirmation from Topstep support before running live.

## Phases (one at a time)
1. Data: 5-8 years of ES/NQ 1-minute bars (Databento, CME Globex OHLCV-1m).
2. Backtester with Topstep rules built in: $2,000 EOD trailing DD (50K), $3,000 target,
   flat by 4:10 PM ET, commission + 1 tick slippage per side, contract limits.
3. Test candidates, in-sample 2018-2022, out-of-sample 2023-2026:
   a. Intraday momentum / noise-area breakout (Zarattini, Aziz, Barbon 2024)
   b. Opening Range Breakout 5/15/30 min (Zarattini & Aziz 2023)
   c. Market intraday momentum, first 30 min -> last 30 min (Gao, Han, Li, Zhou 2018)
   d. VWAP mean reversion (for comparison)
   Key metric: % of simulated Combines passed vs blown, not just total return.
4. Pick 1 strategy that survives out-of-sample. If none survives, stop - don't buy an eval.
5. Bot: Python on Mac Mini -> ProjectX API. Every entry sent as a bracket order (stop at exchange).
   Kill switch at daily loss limit. Logs every order.
6. Practice account paper run: 4+ weeks, live results must match backtest.
7. Buy Topstep 50K Combine. Cancel subscription the day it passes.

## Results log

### Run 1 - 27 Sep 2026 (Dukascopy index CFD 1-min, 2016-2026, costs 1 tick slip/side + $0.75/side)
Paper parameters, no optimisation. IS = 2016-21, OOS = 2022-26. $/1 micro after costs.

| Strategy | Mkt | IS avg$ / PF / Sharpe | OOS avg$ / PF / Sharpe | Verdict |
|---|---|---|---|---|
| NOISE  | MNQ | +5.4 / 1.22 / 1.24 | +8.6 / 1.14 / 0.90 | Candidate #1 |
| ORB5   | MNQ | +3.0 / 1.10 / 0.47 | +9.5 / 1.13 / 0.61 | Candidate #2 |
| ORB30  | MNQ | -1.3 / 0.97 | +18.0 / 1.18 | Regime-dependent, reject |
| LAST30 | MNQ | negative | negative | Reject |
| VWAPMR | MNQ | negative | negative | Reject |
| All 5  | MES | ~0 or negative after costs | | S&P too slow for costs |

Combine pass rate (50K, $3k target, $2k EOD trailing MLL, 50% consistency), full period:
NOISE ~23-27%, ORB5 ~24-37% vs zero-edge baseline 13-28%. Median 60-300 sessions to pass.
=> Edge is real but thin; ~70% of Combines still fail. Next: improve pass rate (trade filters,
risk per trade), then confirm on real MNQ futures data before any money.

### Run 2 - NOISE tuning for Combine pass rate (MNQ, tuned on 2016-21 only, checked on 2022-26)
Combine now counts as FAILED if not passed within 60 sessions (~3 months of fees).
Grid: check every 15/30 min, hard intrabar stop yes/no, max 1/2/unlimited trades per day,
size = $400-2400 per average daily range; then daily loss stop (400/700) and daily profit cap (1000/1400).

Best IS config = the paper default: 30-min checks, no hard stop, unlimited trades, $1600 per avg daily range (~11 MNQ).
  IS  pass 26.7% (zero-edge baseline 19.9%), median 25 sessions to pass
  OOS pass 32.8% (baseline 19.8%), median 31 sessions
Hard stops, trade caps, daily loss stop and profit cap did NOT improve pass rate (loss stop made it worse -
momentum needs room). Ceiling with this strategy is ~25-33% per Combine.
Economics: ~1 pass per 3-4 attempts, ~1-2 months each => roughly $250-450 fees + activation per funded account.

## Rule Guard (manual trading) - futures/rule_guard.py
Read-only watcher on TopstepX API: never places orders. Alerts (terminal + Mac notification + voice) before:
MLL breach incl. unrealized, personal daily loss limit, size > 50 micro-equiv (incl. pending orders),
position without stop, stop placed below MLL floor, 3:10 PM CT flat time, 55% consistency target raise.
`check` command = pre-trade GO / NO-GO. Topstep consistency is now 55% of total profit (runs 1-2 used 50%,
so those pass rates are slightly conservative).

## STATUS (27 Sep 2026) - start here next session
Done:
- Firm research: Topstep #1 (official bot API, EOD MLL, India payout = SWIFT wire $30). MFFU backup. Apex out (bans bots).
- Backtest + tuning: NOISE on MNQ = only candidate. Combine pass ~25-33% (luck ~20%).
- rule_guard.py on RB's Mac at ~/RB_Screener/futures (demo works). Supports 50k/100k/150k Combine via --size,
  multiple accounts via --account (one Terminal window per account), `list` shows account names.
- Screener actually lives at ~/RB_Screener (home), not Desktop. rbscan alias not set up on this Mac.
Next step (waiting on RB): Topstep account made (28 Sep). Practice account is NOT free - needs an active Combine.
Full rules in futures/TOPSTEP_RULES.md. Before paying: email support (India eligibility + bot OK).
After that: install requests, create topstep_login.txt, run guard live on Practice; then NOISE signal mode.
Guard now has XFA mode (--stage xfa --path standard|consistency --payout-since --dll): 40% early warning,
winning days, payout eligibility/amount, scaling plan (50K verified; 100K/150K use 50K table until verified).

### Run 3 - ICT / SMC ideas (smc_test.py), fixed rules, no tuning, $250 risk/trade
AMD_LDN (Asia range -> London sweep -> NY reversal), AMD_NY (overnight range sweep 9:30-11:00, 5-min close back
inside -> reverse), SWEEP_PD (prev-day high/low sweep reversal), each with 2R target and hold-to-close.
Result: NO edge. Before costs, average trade = -0.10R to +0.14R and the sign flips between 2016-21 and 2022-26
(pure noise). After costs every variant loses on MNQ and MES; Combine pass 0-10%, at or below luck.
Order flow NOT tested: needs tick data with aggressor side (bid/ask volume); 1-min price data can't do it.
=> Rejected. NOISE stays the only candidate.

## Hola Prime check (28 Sep 2026) - verdict: NOT primary, maybe later as small second firm
- Founded Oct/Nov 2024 (under 2 years), HQ Comoros, FSC Mauritius dealer licence; forex/CFD firm with a futures arm.
- Futures 1-Step: 6% target, 4% trailing max loss (3% on 100K/150K), no DLL, 40% consistency in eval.
  Direct Account (no eval): 2.5% DLL, 20% consistency. Platforms Tradovate / NinjaTrader / WealthCharts.
- Payout methods include Rise and bank transfer (good for India); claims 1-hour payouts.
- Red flags: Trustpilot removed ~1,300 reviews (early 2025) for guideline breaches; payout denials/closures citing
  discretionary "gambling", "2% risk rule", margin use - some reversed only after public escalation.
- Bot/automation rules for futures not published. No official funnel stats like Topstep's.

### Run 4 - profit-lock / small target exits on NOISE entries (giveback_test.py), MNQ ~11 micros, 55% consistency
| Exit rule | win% IS/OOS | avg$/trade IS/OOS | Combine pass% IS/OOS |
|---|---|---|---|
| NOISE as tested (no lock) | 37/39 | +26/+26 | 28.8/35.9 |
| lock after +$100, exit on 10% giveback (RB idea) | 76/77 | -10/+1 | 15.3/17.2 |
| lock after +$300, exit on 30% giveback | 59/58 | +2/+6 | 24.2/26.0 |
| lock after +$500, exit on 50% giveback | 47/47 | +12/+27 | 28.8/37.8 |
| fixed +$500 target (1% of 50K) | 50/49 | +2/+12 | 20.9/33.2 |
First run of RB idea showed 34-45% pass but used an optimistic same-bar assumption (peak from bar high, then exit
at lock in the same bar). Conservative version (lock from previous bars, gap fills at open) above = the real answer.
Tight profit locks raise win rate but kill the big winners that pay for the losers. Also: Combine MLL is EOD, an
intraday open-profit peak does NOT move the MLL, so locking +$90 of a +$100 trade isn't needed for drawdown.

## FundedNext Futures Rapid check (1 Oct 2026) - strong BACKUP (replaces MFFU as #2)
- UAE firm, founded 2022 (forex first; futures arm newer). Rapid Pro/Daily launched July 2026 (rules churn).
- 50K Rapid: $159.99 ONE-TIME (discounted), target $3,000, MLL $2,000 EOD trailing, can pass in 1 day,
  NO consistency in the challenge. Daily: $1,000 DLL, daily payouts, buffer first. Pro: no DLL, 40% consistency
  when funded, payout every 3 days. Cap per cycle $800/$1,200/$2,500 (25/50/100K), min $500 profit/cycle, 90%.
- Bots/EAs officially allowed (Tradovate integrations); no tech support; no latency/order-flood abuse.
- Payouts: Rise, bank transfer, USDT/USDC, ~24h. India is a top country by payouts.
- Tradovate only (Python bot needs Tradovate API or a webhook bridge - verify access for prop accounts).
- NOISE sim on Rapid rules (no consistency, 40 micros, 60-session limit): pass 34.7% (2016-21) / 45.0% (2022-26)
  vs Topstep 28.8% / 35.9%. Median days to pass 18 / 27.5 vs 23 / 31.

## Apex Trader Funding re-check (1 Oct 2026, "Apex 4.0" since 1 Mar 2026) - #3, only for MANUAL trading
- 50K EOD: $197 eval (often ~90% off, ~$20-49) + $99 PA activation. Intraday-trail 50K: $131 + $79. No monthly fee.
- Target $3,000, $2,000 EOD trailing, $1,000 DLL (soft). Eval EXPIRES in 30 days, no resets/extensions.
- PA payouts: 5 qualifying days, no day > 50% of profit since last payout, balance > start + DD + $100.
  50K ladder: 1st payout cap $1,500 ... 6th $3,000, then the PA CLOSES (lifetime cap). 100% split inside the cap.
- Automation/AI/bots banned on ALL account types (semi-automated tools only). Max 20 accounts. Metals suspended.
- International payouts via Plane (Deel/Wise dropped 2026); India support not confirmed.
- NOISE sim on Apex EOD rules (no eval consistency, $1,000 DLL, 21-session expiry): pass 17.2% / 16.4%
  (vs Topstep 28.8/35.9, FundedNext 34.7/45.0). The 30-day expiry is the killer.
- Cheap on promo: ~$20 eval / 0.17 pass + $99 = ~$220 per PA. But no bot, payouts capped, account dies after 6 payouts.
