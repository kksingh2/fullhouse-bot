"""6-max preflop ranges encoded as sets of 169 hand-strings.

Sources: RangeConverter free 6-max 100bb charts + Red Chip Poker free GTO charts,
simplified to discrete include/exclude (no mixed frequencies). These are
approximations — Day 1 strategy doesn't need perfect ranges, it needs *consistent*
ones. The exploit layer handles deviations.
"""
from typing import List, Set
from .hand_eval import hand_169


def _expand(spec: str) -> Set[str]:
    """Tiny range-string expander.
    Supported forms:
      'AA', 'AKs', 'AKo'                       — single hand
      '22+'                                    — pairs from 22 up
      '77+'                                    — pairs from 77 up
      'A2s+', 'A2o+'                           — suited/offsuit Ax from 2 up
      'KTs-K8s'                                — explicit range
    """
    out: Set[str] = set()
    spec = spec.strip()
    ranks = "23456789TJQKA"

    if "-" in spec:
        a, b = spec.split("-")
        # K9s-K6s style
        if len(a) == 3 and len(b) == 3 and a[0] == b[0] and a[2] == b[2]:
            high = a[0]
            suit = a[2]
            r1, r2 = a[1], b[1]
            i1, i2 = ranks.index(r1), ranks.index(r2)
            for i in range(min(i1, i2), max(i1, i2) + 1):
                out.add(high + ranks[i] + suit)
            return out

    if spec.endswith("+"):
        body = spec[:-1]
        if len(body) == 2 and body[0] == body[1]:  # "22+"
            i = ranks.index(body[0])
            for j in range(i, len(ranks)):
                out.add(ranks[j] + ranks[j])
            return out
        if len(body) == 3:  # "A2s+", "K9o+"
            high, low, suit = body[0], body[1], body[2]
            hi_i = ranks.index(high)
            lo_i = ranks.index(low)
            for j in range(lo_i, hi_i):
                out.add(high + ranks[j] + suit)
            return out

    out.add(spec)
    return out


def _build(specs: List[str]) -> Set[str]:
    out: Set[str] = set()
    for s in specs:
        out |= _expand(s)
    return out


# RFI (open-raise first-in) ranges, 6-max 100bb
RFI = {
    "UTG": _build([
        "22+", "ATs+", "KTs+", "QTs+", "JTs", "T9s", "98s", "AJo+", "KQo"
    ]),  # ~14%
    "MP": _build([
        "22+", "A8s+", "K9s+", "Q9s+", "J9s+", "T9s", "98s", "87s",
        "ATo+", "KJo+", "QJo"
    ]),  # ~17%
    "CO": _build([
        "22+", "A2s+", "K7s+", "Q8s+", "J8s+", "T8s+", "97s+", "86s+", "75s+", "65s",
        "ATo+", "KTo+", "QTo+", "JTo"
    ]),  # ~26%
    "BTN": _build([
        "22+", "A2s+", "K2s+", "Q4s+", "J6s+", "T6s+", "96s+", "85s+", "74s+", "64s+", "53s+",
        "A2o+", "K8o+", "Q9o+", "J9o+", "T8o+", "98o", "87o", "76o"
    ]),  # ~45%
    "SB": _build([
        "22+", "A2s+", "K3s+", "Q6s+", "J7s+", "T7s+", "97s+", "86s+", "75s+", "64s+", "54s",
        "A4o+", "K9o+", "Q9o+", "J9o+", "T9o", "98o"
    ]),  # ~38%
}

# 3-bet (re-raise) value ranges by (hero_position, opener_position)
THREEBET_VALUE = {
    ("BB", "BTN"): _build(["TT+", "AQs+", "AKo"]),
    ("BB", "CO"):  _build(["JJ+", "AQs+", "AKo"]),
    ("BB", "MP"):  _build(["QQ+", "AKs", "AKo"]),
    ("BB", "UTG"): _build(["KK+", "AKs"]),
    ("SB", "BTN"): _build(["TT+", "AQs+", "AKo"]),
    ("SB", "CO"):  _build(["JJ+", "AQs+", "AKo"]),
    ("BTN", "CO"): _build(["JJ+", "AQs+", "AKo"]),
    ("BTN", "MP"): _build(["QQ+", "AKs", "AKo"]),
    ("CO", "MP"):  _build(["QQ+", "AKs", "AKo"]),
}

# 3-bet bluff candidates (hands we randomly mix as 3-bets at threebet_bluff_freq)
THREEBET_BLUFF_CANDIDATES = {
    ("BB", "BTN"): _build(["A5s", "A4s", "A3s", "K9s", "Q9s", "J9s", "76s", "65s"]),
    ("BB", "CO"):  _build(["A5s", "A4s", "K9s", "76s", "65s"]),
    ("BTN", "CO"): _build(["A5s", "A4s", "76s", "65s", "54s"]),
    ("SB", "BTN"): _build(["A5s", "A4s", "A3s", "K9s", "Q9s", "76s", "65s"]),
}

# Call-vs-open ranges (just hand sets; we still need 3bet logic)
CALL_VS_OPEN = {
    ("BB", "BTN"): _build([
        "22+", "A2s+", "K6s+", "Q8s+", "J7s+", "T7s+", "96s+", "85s+", "75s+", "64s+", "54s",
        "A2o+", "K9o+", "Q9o+", "J9o+", "T9o"
    ]),
    ("BB", "CO"):  _build([
        "22+", "A2s+", "K7s+", "Q8s+", "J8s+", "T8s+", "97s+", "86s+", "75s+", "65s",
        "A8o+", "KTo+", "QTo+", "JTo"
    ]),
    ("BB", "MP"):  _build([
        "22+", "A2s+", "K8s+", "Q9s+", "J9s+", "T9s", "98s", "87s",
        "A9o+", "KJo+", "QJo"
    ]),
    ("BB", "UTG"): _build([
        "22+", "A8s+", "K9s+", "QTs+", "JTs", "T9s",
        "AJo+", "KQo"
    ]),
}

# Nash push ranges by effective stack in BB (very simplified)
PUSH_RANGES_BY_BB = {
    15: _build(["22+", "A2s+", "K7s+", "Q9s+", "JTs", "A8o+", "KJo+", "QJo"]),
    12: _build(["22+", "A2s+", "K5s+", "Q8s+", "J9s+", "A5o+", "KTo+", "QTo+", "JTo"]),
    10: _build(["22+", "A2s+", "K2s+", "Q5s+", "J7s+", "T8s+", "A2o+", "K9o+", "Q9o+", "J9o+", "T9o"]),
    8:  _build(["22+", "A2s+", "K2s+", "Q2s+", "J5s+", "T7s+", "97s+", "A2o+", "K6o+", "Q8o+", "J8o+", "T8o+", "98o"]),
    5:  _build(["22+", "A2s+", "K2s+", "Q2s+", "J2s+", "T5s+", "95s+", "85s+", "75s+", "65s",
                "A2o+", "K2o+", "Q4o+", "J6o+", "T7o+", "97o+", "87o"]),
}


def in_range(hole: List[str], range_set: Set[str]) -> bool:
    return hand_169(hole) in range_set


def push_range_for_bb(eff_bb: int) -> Set[str]:
    # round down to nearest known threshold
    keys = sorted(PUSH_RANGES_BY_BB.keys())
    chosen = keys[0]
    for k in keys:
        if k <= eff_bb:
            chosen = k
    return PUSH_RANGES_BY_BB[chosen]
