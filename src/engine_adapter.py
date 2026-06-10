"""Normalize the Fullhouse engine's game_state dict into a typed GameState.

The engine schema (per uzlez/fullhouse-engine README, May 2026):
  your_cards: ["As","Kh"]
  community_cards: list[str]
  street: "preflop"|"flop"|"turn"|"river"
  pot: int
  your_stack: int
  amount_owed: int
  can_check: bool
  current_bet: int
  min_raise_to: int
  players: list of dicts (public info, exact schema TBD on first run)
  action_log: list of dicts (per-action history)

Defensive: any missing key returns a sensible default. The schema MAY differ
from the README; the first action of the first scrimmage will print a sample
so we can adjust.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass
class PlayerView:
    seat: int = -1
    stack: int = 0
    in_hand: bool = True
    has_folded: bool = False
    contributed_total: int = 0
    is_hero: bool = False


@dataclass
class GameState:
    raw: Dict[str, Any]
    hand_id: int
    street: str
    your_cards: List[str]
    community_cards: List[str]
    pot: int
    your_stack: int
    amount_owed: int
    can_check: bool
    current_bet: int
    min_raise_to: int
    max_raise_to: int
    big_blind: int
    players: List[PlayerView]
    action_log: List[Dict]
    hero_seat: int
    button_seat: int
    n_active: int

    @property
    def spr(self) -> float:
        return self.your_stack / max(self.pot, 1)

    @property
    def position(self) -> str:
        """6-max position label. Falls back gracefully if seat info missing."""
        if self.button_seat < 0 or self.hero_seat < 0:
            return "UNK"
        # active seats around table
        active_seats = [p.seat for p in self.players if p.in_hand]
        if not active_seats:
            return "UNK"
        n = len(active_seats)
        # offset from button (BTN=0, SB=1, BB=2, ...)
        try:
            order = sorted(active_seats)
            btn_idx = order.index(self.button_seat) if self.button_seat in order else 0
            hero_idx = order.index(self.hero_seat) if self.hero_seat in order else 0
            offset = (hero_idx - btn_idx) % n
        except ValueError:
            return "UNK"
        # Standard 6-max names
        names_by_n = {
            6: ["BTN", "SB", "BB", "UTG", "MP", "CO"],
            5: ["BTN", "SB", "BB", "UTG", "CO"],
            4: ["BTN", "SB", "BB", "CO"],
            3: ["BTN", "SB", "BB"],
            2: ["BTN", "BB"],
        }
        labels = names_by_n.get(n, ["UNK"] * n)
        return labels[offset] if offset < len(labels) else "UNK"


def _safe_int(v, default=0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _parse_player(p: Any, hero_marker=None) -> PlayerView:
    if not isinstance(p, dict):
        return PlayerView()
    return PlayerView(
        seat=_safe_int(p.get("seat", -1), -1),
        stack=_safe_int(p.get("stack", 0)),
        in_hand=bool(p.get("in_hand", not p.get("folded", False))),
        has_folded=bool(p.get("folded", False) or p.get("has_folded", False)),
        contributed_total=_safe_int(p.get("contributed_total", p.get("total_bet", 0))),
        is_hero=bool(p.get("is_hero", False)),
    )


def normalize(raw: Dict[str, Any]) -> GameState:
    your_cards = list(raw.get("your_cards", []) or [])
    community = list(raw.get("community_cards", []) or [])
    pot = _safe_int(raw.get("pot", 0))
    your_stack = _safe_int(raw.get("your_stack", 0))
    amount_owed = _safe_int(raw.get("amount_owed", 0))
    can_check = bool(raw.get("can_check", amount_owed == 0))
    current_bet = _safe_int(raw.get("current_bet", 0))
    min_raise_to = _safe_int(raw.get("min_raise_to", max(current_bet * 2, 2)))
    max_raise_to = _safe_int(raw.get("max_raise_to", your_stack + amount_owed))
    big_blind = _safe_int(raw.get("big_blind", 2))
    street = str(raw.get("street", "preflop")).lower()

    players_raw = raw.get("players", []) or []
    players = [_parse_player(p) for p in players_raw]
    n_active = sum(1 for p in players if p.in_hand and not p.has_folded) or max(2, len(players))

    hero_seat = _safe_int(raw.get("hero_seat", raw.get("your_seat", -1)), -1)
    button_seat = _safe_int(raw.get("button_seat", raw.get("dealer_seat", -1)), -1)
    hand_id = _safe_int(raw.get("hand_id", raw.get("hand_number", 0)))
    action_log = list(raw.get("action_log", []) or [])

    return GameState(
        raw=raw,
        hand_id=hand_id,
        street=street,
        your_cards=your_cards,
        community_cards=community,
        pot=pot,
        your_stack=your_stack,
        amount_owed=amount_owed,
        can_check=can_check,
        current_bet=current_bet,
        min_raise_to=min_raise_to,
        max_raise_to=max_raise_to,
        big_blind=big_blind,
        players=players,
        action_log=action_log,
        hero_seat=hero_seat,
        button_seat=button_seat,
        n_active=n_active,
    )
