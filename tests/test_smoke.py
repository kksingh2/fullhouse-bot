"""Smoke tests — bot must always emit a legal, well-formed action."""
import os
import sys
import time
import random

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import bot  # noqa: E402


VALID_ACTIONS = {"fold", "check", "call", "raise", "all_in"}


def _state(**overrides):
    base = {
        "your_cards": ["As", "Kh"],
        "community_cards": [],
        "street": "preflop",
        "pot": 30,
        "your_stack": 1000,
        "amount_owed": 20,
        "can_check": False,
        "current_bet": 20,
        "min_raise_to": 40,
        "max_raise_to": 1000,
        "big_blind": 10,
        "players": [],
        "action_log": [],
        "hero_seat": 1,
        "button_seat": 0,
    }
    base.update(overrides)
    return base


def test_returns_legal_action_basic():
    out = bot.decide(_state())
    assert out["action"] in VALID_ACTIONS


def test_check_when_free():
    out = bot.decide(_state(amount_owed=0, can_check=True))
    assert out["action"] in {"check", "raise", "all_in"}


def test_handles_garbage_state():
    # Missing nearly everything — should still return a legal action, not crash.
    out = bot.decide({"your_cards": ["7c", "2d"], "amount_owed": 5})
    assert out["action"] in VALID_ACTIONS


def test_random_states_no_crash():
    deck = [r + s for r in "23456789TJQKA" for s in "shdc"]
    for _ in range(200):
        cards = random.sample(deck, 7)
        owed = random.randint(0, 200)
        state = _state(
            your_cards=cards[:2],
            community_cards=cards[2:5] if random.random() < 0.5 else [],
            street=random.choice(["preflop", "flop", "turn", "river"]),
            pot=random.randint(20, 2000),
            your_stack=random.randint(0, 5000),
            amount_owed=owed,
            can_check=(owed == 0),
            current_bet=owed,
            min_raise_to=max(owed * 2, 20),
        )
        out = bot.decide(state)
        assert out["action"] in VALID_ACTIONS


def test_p99_under_1500ms():
    times = []
    for _ in range(200):
        s = _state()
        t0 = time.perf_counter()
        bot.decide(s)
        times.append((time.perf_counter() - t0) * 1000)
    times.sort()
    p99 = times[198]
    assert p99 < 1500, f"p99 = {p99:.0f}ms"
