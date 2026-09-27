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
Next step (waiting on RB): make free Topstep account, check (a) free Practice account without buying Combine,
(b) can API subscription ($14.50/mo) be bought without a Combine.
After that: install requests, create topstep_login.txt, run guard live on Practice; then NOISE signal mode.
Not done yet: Express Funded rules in guard (40% payout consistency, scaling plan) - verify then add.

### Run 3 - ICT / SMC ideas (smc_test.py), fixed rules, no tuning, $250 risk/trade
AMD_LDN (Asia range -> London sweep -> NY reversal), AMD_NY (overnight range sweep 9:30-11:00, 5-min close back
inside -> reverse), SWEEP_PD (prev-day high/low sweep reversal), each with 2R target and hold-to-close.
Result: NO edge. Before costs, average trade = -0.10R to +0.14R and the sign flips between 2016-21 and 2022-26
(pure noise). After costs every variant loses on MNQ and MES; Combine pass 0-10%, at or below luck.
Order flow NOT tested: needs tick data with aggressor side (bid/ask volume); 1-min price data can't do it.
=> Rejected. NOISE stays the only candidate.
