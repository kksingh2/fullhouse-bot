"""Orchestrator. Maps GameState → action via priority cascade."""
import time
import random
from typing import Optional

from .ranges import (RFI, THREEBET_VALUE, THREEBET_BLUFF_CANDIDATES,
                     CALL_VS_OPEN, in_range, push_range_for_bb)
from .hand_eval import hand_169, equity_vs_random, preflop_equity_vs_random
from .postflop import (cbet_action, call_or_fold, value_raise_or_call,
                       should_stack_off, pot_odds_required_equity)
from .boards import classify
from .exploit_layer import adjust as exploit_adjust
from .safety import safe_default


def _last_aggressor_position(gs) -> Optional[str]:
    """Position of the last preflop raiser (best-effort)."""
    for ev in reversed(gs.action_log):
        if not isinstance(ev, dict):
            continue
        if ev.get("street") not in (None, "preflop"):
            continue
        if ev.get("action") in ("raise", "bet"):
            seat = ev.get("seat", ev.get("player"))
            if seat is None or seat == gs.hero_seat:
                continue
            # crude position label by seat-vs-button
            try:
                seat = int(seat)
            except (TypeError, ValueError):
                return None
            offset = (seat - gs.button_seat) % max(gs.n_active, 2)
            labels = {0: "BTN", 1: "SB", 2: "BB", 3: "UTG", 4: "MP", 5: "CO"}
            return labels.get(offset, "UNK")
    return None


def _preflop(gs, cfg, model):
    h169 = hand_169(gs.your_cards)
    pos = gs.position
    eff_bb = max(gs.your_stack, 1) / max(gs.big_blind, 1)

    # Short-stack push/fold
    if eff_bb <= cfg.preflop.push_fold_threshold_bb:
        push_range = push_range_for_bb(int(eff_bb))
        if h169 in push_range:
            return {"action": "all_in"}
        if gs.can_check:
            return {"action": "check"}
        return {"action": "fold"}

    aggressor = _last_aggressor_position(gs)

    # Facing a raise → 3-bet/call/fold
    if gs.amount_owed > gs.big_blind:
        if aggressor and (pos, aggressor) in THREEBET_VALUE:
            value = THREEBET_VALUE[(pos, aggressor)]
            bluff = THREEBET_BLUFF_CANDIDATES.get((pos, aggressor), set())
            if h169 in value:
                amount = max(gs.min_raise_to, int(round(gs.amount_owed * cfg.preflop.threebet_size_xpot)))
                if gs.max_raise_to:
                    amount = min(amount, gs.max_raise_to)
                return {"action": "raise", "amount": amount}
            if h169 in bluff and random.random() < cfg.preflop.threebet_bluff_freq:
                amount = max(gs.min_raise_to, int(round(gs.amount_owed * cfg.preflop.threebet_size_xpot)))
                if gs.max_raise_to:
                    amount = min(amount, gs.max_raise_to)
                return {"action": "raise", "amount": amount}
            call_set = CALL_VS_OPEN.get((pos, aggressor), set())
            if h169 in call_set:
                # Pot odds sanity check vs estimated villain range equity
                eq = preflop_equity_vs_random(gs.your_cards)
                needed = pot_odds_required_equity(gs.amount_owed, gs.pot - gs.amount_owed)
                # vs raiser's range we lose ~5% equity vs random; require eq >= needed + 0.04
                if eq >= needed + 0.04:
                    return {"action": "call"}
            return {"action": "fold"}
        # unknown opponent position: tight default
        if h169 in {"AA", "KK", "QQ", "JJ", "AKs", "AKo", "AQs"}:
            amount = max(gs.min_raise_to, int(round(gs.amount_owed * 3.0)))
            return {"action": "raise", "amount": amount}
        if h169 in {"TT", "99", "AQo", "AJs", "KQs"}:
            return {"action": "call"}
        return {"action": "fold"}

    # First in (no raise yet) — open or limp/fold
    if pos in RFI and h169 in RFI[pos]:
        amount = max(gs.min_raise_to, int(round(gs.big_blind * cfg.preflop.open_size_bb)))
        return {"action": "raise", "amount": amount}

    # BB free check (no one raised, just SB completion)
    if gs.can_check:
        return {"action": "check"}
    return {"action": "fold"}


def _postflop(gs, cfg, model, deadline_s):
    # MC trial budget by street
    budget = {
        "flop": cfg.timing.mc_budget_flop,
        "turn": cfg.timing.mc_budget_turn,
        "river": cfg.timing.mc_budget_river,
    }.get(gs.street, 300)

    n_villains = max(gs.n_active - 1, 1)
    eq = equity_vs_random(gs.your_cards, gs.community_cards,
                          n_villains=n_villains, trials=budget, deadline_s=deadline_s)

    # Facing a bet
    if gs.amount_owed > 0:
        # Stack-off check
        if gs.amount_owed >= gs.your_stack * 0.5:
            if should_stack_off(gs, cfg, eq):
                return {"action": "all_in"}
            if gs.can_check:
                return {"action": "check"}
            return {"action": "fold"}
        if eq >= 0.70:
            return value_raise_or_call(gs, cfg, eq)
        return call_or_fold(gs, cfg, eq)

    # No bet to face — checked to us / we have initiative
    return cbet_action(gs, cfg, eq, deadline_s)


def act(gs, cfg, model, deadline_s):
    if time.perf_counter() > deadline_s - 0.1:
        return safe_default(gs)

    if gs.street == "preflop":
        base = _preflop(gs, cfg, model)
    else:
        base = _postflop(gs, cfg, model, deadline_s)

    final = exploit_adjust(base, gs, cfg, model)
    return final
