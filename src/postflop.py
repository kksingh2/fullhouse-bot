"""Postflop primitives: pot odds, MDF, c-bet, call/fold facing bet, stack-off."""
from typing import Optional
from .boards import classify, is_dry
from .hand_eval import equity_vs_random


def pot_odds_required_equity(amount_owed: int, pot_before_call: int) -> float:
    """Equity needed to break-even on a call. Pot includes all chips currently in."""
    if amount_owed <= 0:
        return 0.0
    return amount_owed / (pot_before_call + amount_owed)


def mdf(bet_size_pot_fraction: float) -> float:
    """Minimum defense frequency vs a bet of size s pot. = 1/(1+s)."""
    return 1.0 / (1.0 + max(bet_size_pot_fraction, 0.001))


def alpha(bet_size_pot_fraction: float) -> float:
    """Bluff freq making opponent indifferent. = s/(1+s)."""
    return bet_size_pot_fraction / (1.0 + bet_size_pot_fraction)


def cbet_action(gs, cfg, equity: float, deadline_s: Optional[float] = None):
    """Decide whether to c-bet (we have initiative, no bet to face)."""
    tex = classify(gs.community_cards)
    pot = max(gs.pot, gs.big_blind)

    if is_dry(tex):
        freq = cfg.postflop.cbet_freq_dry
        size_xpot = cfg.postflop.cbet_size_dry_xpot
    else:
        freq = cfg.postflop.cbet_freq_wet
        size_xpot = cfg.postflop.cbet_size_wet_xpot

    # We always cbet when we have a real value hand (>55% equity vs random).
    # Otherwise mix at freq.
    import random
    if equity >= 0.55 or random.random() < freq:
        amount = int(round(pot * size_xpot * cfg.sizing.max_bet_size_pot))
        amount = max(amount, gs.min_raise_to)
        return {"action": "raise", "amount": amount}
    return {"action": "check"}


def call_or_fold(gs, cfg, equity: float):
    """Facing a bet. Use pot odds + MDF buffer."""
    pot_before = gs.pot - gs.amount_owed
    needed = pot_odds_required_equity(gs.amount_owed, pot_before)
    buffer = cfg.defense.mdf_buffer

    # Call if equity >= needed + buffer.
    if equity >= needed + buffer:
        return {"action": "call"}
    if gs.can_check:
        return {"action": "check"}
    return {"action": "fold"}


def value_raise_or_call(gs, cfg, equity: float):
    """Strong hand facing a bet. Raise for value if equity high enough."""
    pot = max(gs.pot, gs.big_blind)
    if equity >= 0.75 and gs.your_stack > gs.amount_owed * 2:
        amount = int(round((gs.pot + gs.amount_owed) * 0.75))
        amount = max(amount, gs.min_raise_to)
        amount = int(min(amount, pot * cfg.sizing.max_bet_size_pot + gs.amount_owed))
        return {"action": "raise", "amount": amount}
    return {"action": "call"}


def should_stack_off(gs, cfg, equity: float) -> bool:
    return equity >= cfg.stack_off.allin_threshold_equity
