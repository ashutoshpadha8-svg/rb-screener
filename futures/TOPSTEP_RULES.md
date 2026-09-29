# Topstep - full rules research (read from help.topstep.com, 28 Sep 2026)

Topstep changes rules often. Re-check the help center before buying anything.

## Eligibility (India)
- India is NOT on the ineligible list and NOT on the "XFA only" list -> India appears eligible for Combine, XFA and Live.
  Confirm with support before paying.
- 18+. ID verification after first purchase: original physical passport / driving licence / national ID + selfie.
  Use the passport (name must match PAN/bank for payouts). No VPN - location mismatch breaks verification and is banned.
- Non-US traders fill W-8BEN. No US tax withheld info given; report in India (see earlier tax notes, get a CA).

## Prices (checkout page + pricing article)
| Size | Standard /month | Activation (per XFA, one-time) | No-Activation-Fee /month | With DLL ("Responsible Trading") |
|---|---|---|---|---|
| 50K  | $49  | $149 | $95 ($85 with DLL)  | payout caps x2 |
| 100K | $99  | $149 | $149 ($129 with DLL) | payout caps x2 |
| 150K | $199 | $149 | $229 ($199 with DLL) | payout caps x2 |
- Reset = same as one month's fee. Every monthly rebill gives 1 free Reset credit (expires after 1 year). Max 2 resets/account/day.
- Rebills every 30 days until you pass or cancel. Passing auto-cancels that subscription. Cancelled = gone for good.
- Level 2 data $38/month (optional, not needed). TopstepX platform free. Cards: Visa/Mastercard/Amex/Discover, Apple/Google Pay. GST/VAT may be added.
- Refunds: 14-day guarantee (one monthly fee, only if not passed). Resets, activation, L2 data, Back2Funded = no refund.
  Chargeback = ban.
- Practice account: FREE only WITH an active Combine ($150K sim, 15 lots, 10 resets/day). No free practice without buying.
- API (ProjectX): $29/month, $14.50 with code "topstep". Combine + XFA only, NOT Live. No VPS/VPN; orders from own device.

## Trading Combine (the exam)
| | 50K | 100K | 150K |
|---|---|---|---|
| Profit target | $3,000 | $6,000 | $9,000 |
| Max Loss Limit (EOD trailing, locks at start) | $2,000 | $3,000 | $4,500 |
| Max contracts | 5 mini / 50 micro | 10 / 100 | 15 / 150 |
| Optional DLL (soft: flattens, back next session) | $1,000 | $2,000 | $3,000 |
- MLL checked in real time on realized + UNREALIZED P&L -> instant liquidation. Slippage past MLL is your problem.
- Consistency 55%: best day's profit vs total. If a day is too big the target rises (e.g. $1,800 day -> need $3,273).
  Best day locks at 3:10 PM CT.
- Trading day 5:00 PM CT -> 3:10 PM CT. Flat by 3:10 PM CT (auto-flatten starts 3:10; don't open after 3:08).
  No overnight / weekend holding. Futures only (no forex).
- No minimum-days rule found in 2026 docs; no time limit (you pay monthly until pass).

## Express Funded Account (XFA) - first account that pays
- Starts at $0 balance (Combine profit does NOT carry over). MLL starts at -$2,000 (50K) and trails EOD, locks at $0.
- AFTER EVERY PAYOUT: MLL resets to $0 permanently. Buffer = only what you leave in the account. Big trap.
- Scaling plan (50K): 2 minis/20 micros at start, 3 minis at $1,500 balance, 5 minis at $2,000. Limit changes next
  session only. Over the limit for 10+ seconds = review.
- Max 5 active XFAs. No trading for 30+ days = account can be closed.
- Payout paths:
  - Standard: 5 winning days of $150+ (non-consecutive), up to 50% of balance, cap $2,000 (50K) / $3,000 / $5,000.
  - Consistency: 3 trading days, best day <= 40% of profit, cap $3,000 / $4,000 / $6,000.
  - DLL chosen at purchase -> caps doubled.
- Split: 90/10 from the first dollar for accounts joined on/after 12 Jan 2026 (support confirmed 28 Sep 2026).
- India payout: Wire/SWIFT, $30 fee, 5-10 business days. (Rise/Wise not offered for India.)
- Back2Funded: lost XFA before any payout -> reactivate for $599/$699/$829 (max 2 times, 30-day window).

## Live Funded Account
- Only by Topstep Risk Team invitation (consistency, stops, sizing, payout history). Cannot be bought.
- Account size = average of your XFAs; you get 20% now (min $10K), 80% in reserve released as you hit targets.
  XFA balances above the Live account size are FORFEITED on call-up.
- Live costs: pro market data $133/month per exchange (CME covered), NQ/ES $3.80 RT, own platform licence.
- Daily loss limit mandatory ($2,000 / $3,000 / $4,500). Balance < $1,000 = closed.
- Call-down back to sim for drawdowns, revenge trading, over-leverage.

## Commissions (TopstepX, Combine/XFA)
MNQ / MES $1.22 round turn. NQ / ES $3.78 round turn. (Our backtests assumed $1.50 + 2 ticks slippage for micros - conservative.)

## Banned (read before trading)
- Cross-account hedging (long in one account, short in another, same/correlated product). Payouts forfeited, no appeal.
- Trading full max size INTO a scheduled major news event. News trading otherwise allowed, but no exceptions for slippage.
- Account stacking (blowing many accounts hoping one hits big). Excessive Combine/Reset buying -> "Focused Trader" restrictions.
- Sim exploitation: scalping for unrealistic fills, hundreds of rapid trades, gap trading for stray fills.
- "Unfair technology: software, AI, ultra-high speed systems that manipulate/abuse/give unfair advantage."
  Official API automation is allowed - get written confirmation that our rule-based bot is fine.
- Trading within 2% of CME price limit. Orders outside best bid/offer. Trading for others / copying others. VPN/proxy.
- During high volatility (CPI etc.) Topstep can temporarily cut contract limits.
- Behaviour: pushing too many Resets, trading without stops, maxing size, revenge trading -> Responsible Trading Program
  (forced DLL, XFA consistency path only) until $10K Live profit.

## Decisions for RB
1. 50K, Standard plan ($49/month). No-Activation-Fee only wins if you pass in < ~4 months: 49m + 149 = 85m -> m = 4.1.
   Our backtest: median ~1-1.5 months per pass attempt, but 2 of 3 attempts fail, so expected total 3-5 months -> Standard.
   Standard also only charges the $149 when you actually pass.
2. DLL ($1,000, "Responsible Trading Advantage") ON: backtest NOISE (MNQ, 60-session limit, 55% consistency):
   pass 28.8% -> 24.8% (2016-21), 35.9% -> 35.5% (2022-26). Small cost, but doubles XFA payout caps. Worth it.
3. First XFA payout: take small (e.g. $500-1,000), leave buffer - MLL goes to $0 after payout.
4. Before paying: email support: (a) India eligible for XFA + Live and SWIFT payouts? (b) rule-based Python bot via
   ProjectX API from own Mac OK under "unfair technology" clause? Keep the written replies.

## Official 2025 funnel stats (Topstep blog "The truth about prop firm payouts")
- 16.8% of all Combines started were passed.
- 51.8% of people who tried at least one Combine reached XFA at least once (many attempts).
- 33.3% of people at Funded level received at least one payout.
- 0.71% of XFA traders were called up to Live.
- 99.26% of payout requests that qualified were approved.
- Profit split conflict: help center says 100% of first $10K for new dashboard users; other sources say flat 90/10
  for accounts created after 12 Jan 2026. Asked support (Gmail draft, 28 Sep 2026).

## What "top traders" do - what can actually be verified
- Topstep does not publish trade logs of top traders. Spotlights/"biggest payout" posts are marketing and survivorship.
- Only verifiable behaviour: what Topstep rewards (stops on every trade, small size vs limits, no revenge trading,
  consistency) and what it punishes (maxing size, stacking accounts, trading into news).
- Research: Chague, De-Losso, Giovannetti (2019/2020), Brazil mini-index futures day traders, 1,551 who traded 300+ days:
  97% lost money, 1.1% earned more than minimum wage; no evidence of learning.

## Support reply (28 Sep 2026, looks like the AI assistant "Windy" - came 2 min after sending)
Confirmed in writing:
- Profit split: accounts joined on/after 12 Jan 2026 = 90/10 from the first dollar (the "100% of first $10K" line is old).
- International payouts: Wire/SWIFT only, 5-10 business days, $30 fee. Wise only for China/Canada/UK. W-8BEN at payout.
- Cards: Visa/Mastercard/Amex/Discover, Apple Pay, Google Wallet. Sales tax may be added at checkout.
- API $14.50/month with code "topstep". Automation must run from own device; VPS/VPN/remote servers banned;
  private server only for research/logging/read-only dashboards.
NOT answered (follow-up drafted asking for a human): India eligibility, bot OK under "unfair technology" rule,
read-only API on XFA/Live, DLL double caps on Standard path, full scaling table, MLL $0 after payout,
US withholding, 14-day guarantee for India, GST.
