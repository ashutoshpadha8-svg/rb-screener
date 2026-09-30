"""Shared position budgeting for live planning and research backtests.

The live default is a fixed initial-capital/slots budget. NAV/slots is an
explicit research option; it is never enabled implicitly by account growth.
Fees and slippage are inputs because a live AMO's eventual fill is unknown.
"""
import math

FIXED_SLOT = "fixed_Rs10000_live_default"
NAV_DIV_SLOTS = "reinvest_NAV_div_20"
DEFAULT_MODE = FIXED_SLOT


def slot_budget(capital, slots, mode=DEFAULT_MODE, nav=None):
    if slots <= 0 or capital <= 0:
        raise ValueError("capital and slots must be positive")
    if mode == FIXED_SLOT:
        return float(capital) / slots
    if mode == NAV_DIV_SLOTS:
        if nav is None or not math.isfinite(float(nav)):
            raise ValueError("NAV sizing requires a finite portfolio value")
        return max(0.0, float(nav)) / slots
    raise ValueError("unknown sizing mode: %s" % mode)


def whole_shares(amount, price, buy_cost=0.0):
    if not price or not math.isfinite(float(price)) or price <= 0:
        return 0
    if buy_cost < 0 or not math.isfinite(float(amount)):
        raise ValueError("invalid amount or buy cost")
    return max(0, int(math.floor(amount / (price * (1 + buy_cost)))))
