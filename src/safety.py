"""Legal-action coercion + panic fallback.

Engine action format (per README):
  {"action": "fold"}
  {"action": "check"}                 # only if can_check
  {"action": "call"}
  {"action": "raise", "amount": N}    # N is the TOTAL bet, not raise-by
  {"action": "all_in"}

Invalid/missing actions auto-fold. Raises below min are snapped up automatically
by the engine, but we snap them ourselves to avoid surprises.
"""
from typing import Dict, Any


def safe_default(gs) -> Dict[str, Any]:
    """Cheapest legal action: check if free, else fold."""
    if gs.can_check:
        return {"action": "check"}
    return {"action": "fold"}


def coerce_action(action: Dict[str, Any], gs) -> Dict[str, Any]:
    """Snap whatever the strategy returned to a legal, well-formed action."""
    if not isinstance(action, dict):
        return safe_default(gs)
    a = action.get("action", "fold")

    if a == "all_in":
        # Always legal as long as we have chips.
        if gs.your_stack <= 0:
            return safe_default(gs)
        return {"action": "all_in"}

    if a == "check":
        if gs.can_check:
            return {"action": "check"}
        # asked to check when we owe chips; downgrade
        return {"action": "fold"}

    if a == "call":
        if gs.amount_owed == 0:
            return {"action": "check"} if gs.can_check else {"action": "fold"}
        # If calling would put us all in, the engine treats call as covering up to stack.
        return {"action": "call"}

    if a == "raise":
        amount = action.get("amount", action.get("size", gs.min_raise_to))
        try:
            amount = int(amount)
        except (TypeError, ValueError):
            amount = gs.min_raise_to
        # If raise would equal/exceed stack -> all-in
        if amount >= gs.your_stack + (gs.current_bet - gs.amount_owed):
            return {"action": "all_in"}
        # snap to min
        amount = max(amount, gs.min_raise_to)
        # snap to max if known
        if gs.max_raise_to and gs.max_raise_to > 0:
            amount = min(amount, gs.max_raise_to)
        return {"action": "raise", "amount": amount}

    if a == "fold":
        # Never fold for free.
        if gs.can_check:
            return {"action": "check"}
        return {"action": "fold"}

    return safe_default(gs)


def panic_action(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Used when normalize() itself raises. Operates on raw dict."""
    if raw and raw.get("can_check"):
        return {"action": "check"}
    return {"action": "fold"}
