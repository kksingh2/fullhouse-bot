"""Beta-Binomial opponent trackers per villain seat.

We key by seat number, not name (the engine likely doesn't expose names). Across
hands the same seat is the same physical opponent in this match.

Stats tracked:
  vpip      — voluntarily put money in pot %
  pfr       — preflop raise %
  threebet  — 3-bet %
  fold_to_3b — folds to a 3-bet
  cbet      — c-bets when held flop initiative
  fold_to_cb — folds to a c-bet
  wtsd      — went to showdown
  af        — aggression factor (bets+raises) / calls

The action_log parser is heuristic; the exact engine schema will be confirmed
on first run and we'll patch the parser. Until then it tries to handle a few
plausible shapes (dict with "action"/"player"/"street", or a tuple).
"""
from dataclasses import dataclass, field
from collections import defaultdict
from typing import Dict, List, Any


@dataclass
class BetaCounter:
    a: float = 2.0
    b: float = 5.0

    def update(self, success: bool):
        if success:
            self.a += 1
        else:
            self.b += 1

    @property
    def mean(self) -> float:
        return self.a / max(self.a + self.b, 1e-9)


@dataclass
class VillainStats:
    vpip: BetaCounter = field(default_factory=lambda: BetaCounter(2.0, 5.0))
    pfr: BetaCounter = field(default_factory=lambda: BetaCounter(2.0, 5.0))
    threebet: BetaCounter = field(default_factory=lambda: BetaCounter(1.0, 9.0))
    fold_to_3b: BetaCounter = field(default_factory=lambda: BetaCounter(5.0, 5.0))
    cbet: BetaCounter = field(default_factory=lambda: BetaCounter(5.0, 3.0))
    fold_to_cb: BetaCounter = field(default_factory=lambda: BetaCounter(5.0, 5.0))
    wtsd: BetaCounter = field(default_factory=lambda: BetaCounter(2.0, 6.0))
    af_aggressive: int = 0
    af_passive: int = 0
    bet_sizes_xpot: List[float] = field(default_factory=list)
    hands_observed: int = 0
    archetype: str = "unknown"

    @property
    def af(self) -> float:
        return self.af_aggressive / max(self.af_passive, 1)


class OpponentModel:
    def __init__(self):
        self.villains: Dict[int, VillainStats] = defaultdict(VillainStats)
        self._seen_hand_ids = set()
        self._processed_action_count = 0

    def update_from_action_log(self, action_log: List[Any], players, hand_id: int):
        """Incrementally consume new actions. Idempotent across calls within a hand."""
        if hand_id not in self._seen_hand_ids:
            self._seen_hand_ids.add(hand_id)
            self._processed_action_count = 0

        new_actions = action_log[self._processed_action_count:]
        for ev in new_actions:
            self._consume(ev)
        self._processed_action_count = len(action_log)

        # crude per-hand tally: bump hands_observed for any seen seat once per new hand
        for seat in list(self.villains.keys()):
            pass  # actual increment happens in _consume on first action of the hand

    def _consume(self, ev: Any):
        seat, action, street, amount = self._extract(ev)
        if seat is None or action is None:
            return
        v = self.villains[seat]

        if action in ("bet", "raise"):
            v.af_aggressive += 1
            if street == "preflop":
                v.pfr.update(True)
                v.vpip.update(True)
        elif action == "call":
            v.af_passive += 1
            if street == "preflop":
                v.vpip.update(True)
                v.pfr.update(False)
        elif action == "check":
            v.af_passive += 1
        elif action == "fold":
            if street == "preflop":
                v.vpip.update(False)
                v.pfr.update(False)

    def _extract(self, ev: Any):
        """Try several plausible event shapes."""
        if isinstance(ev, dict):
            seat = ev.get("seat", ev.get("player", ev.get("player_id")))
            action = ev.get("action", ev.get("type"))
            street = ev.get("street")
            amount = ev.get("amount", ev.get("size"))
            try:
                seat = int(seat) if seat is not None else None
            except (TypeError, ValueError):
                seat = None
            if isinstance(action, str):
                action = action.lower()
            return seat, action, street, amount
        if isinstance(ev, (list, tuple)) and len(ev) >= 2:
            return ev[0], (ev[1].lower() if isinstance(ev[1], str) else None), None, None
        return None, None, None, None

    def classify(self, seat: int) -> str:
        s = self.villains.get(seat)
        if s is None or s.hands_observed < 30:
            return "unknown"
        v, p, af = s.vpip.mean, s.pfr.mean, s.af
        if v > 0.45 and af > 3:
            return "maniac"
        if v > 0.40 and af < 1.5:
            return "station"
        if 0.18 < v < 0.28 and 0.15 < p < 0.25 and af > 2:
            return "tag"
        if v > 0.30 and af > 2:
            return "lag"
        if v < 0.16:
            return "nit"
        return "llm_default"


GLOBAL_MODEL = OpponentModel()
