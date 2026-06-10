"""eval7 wrappers + adaptive Monte Carlo equity.

eval7.evaluate() returns a single int score (higher = better).
Cards are eval7.Card("As") etc.
"""
import time
import random
from typing import List, Optional

try:
    import eval7
    _HAS_EVAL7 = True
except ImportError:
    _HAS_EVAL7 = False
    eval7 = None


def cards_to_eval7(cards: List[str]):
    return [eval7.Card(c) for c in cards]


# --- 169-bucket preflop hand classification ---
RANKS = "23456789TJQKA"
RANK_IDX = {r: i for i, r in enumerate(RANKS)}


def hand_169(hole: List[str]) -> str:
    """Canonical 169-bucket name. e.g. ['Ah','Kd'] -> 'AKo', ['As','Ks'] -> 'AKs', ['7c','7h'] -> '77'."""
    if len(hole) != 2:
        return "??"
    r1, s1 = hole[0][0], hole[0][1]
    r2, s2 = hole[1][0], hole[1][1]
    if RANK_IDX[r1] < RANK_IDX[r2]:
        r1, r2 = r2, r1
        s1, s2 = s2, s1
    if r1 == r2:
        return r1 + r2
    return r1 + r2 + ("s" if s1 == s2 else "o")


# --- Heads-up preflop equity vs random hand (cached approximate values) ---
# Source: well-known computed values (Sklansky/PokerStove). Equity vs random hand HU.
PREFLOP_EQUITY_VS_RANDOM = {
    "AA": 0.852, "KK": 0.824, "QQ": 0.799, "JJ": 0.775, "TT": 0.751,
    "99": 0.720, "88": 0.691, "77": 0.661, "66": 0.633, "55": 0.605,
    "44": 0.578, "33": 0.549, "22": 0.503,
    "AKs": 0.671, "AQs": 0.663, "AJs": 0.654, "ATs": 0.645, "A9s": 0.629,
    "A8s": 0.620, "A7s": 0.610, "A6s": 0.598, "A5s": 0.601, "A4s": 0.594,
    "A3s": 0.585, "A2s": 0.576,
    "KQs": 0.631, "KJs": 0.621, "KTs": 0.611, "K9s": 0.589, "K8s": 0.567,
    "K7s": 0.557, "K6s": 0.547, "K5s": 0.536, "K4s": 0.526, "K3s": 0.517,
    "K2s": 0.508,
    "QJs": 0.601, "QTs": 0.592, "Q9s": 0.571, "Q8s": 0.549, "Q7s": 0.527,
    "Q6s": 0.518, "Q5s": 0.508, "Q4s": 0.498, "Q3s": 0.488, "Q2s": 0.479,
    "JTs": 0.581, "J9s": 0.561, "J8s": 0.539, "J7s": 0.518, "J6s": 0.487,
    "J5s": 0.477, "J4s": 0.467, "J3s": 0.458, "J2s": 0.449,
    "T9s": 0.541, "T8s": 0.520, "T7s": 0.499, "T6s": 0.479, "T5s": 0.448,
    "T4s": 0.439, "T3s": 0.430, "T2s": 0.420,
    "98s": 0.500, "97s": 0.480, "96s": 0.460, "95s": 0.430, "94s": 0.398,
    "87s": 0.461, "86s": 0.441, "85s": 0.412, "84s": 0.382, "83s": 0.354,
    "76s": 0.424, "75s": 0.404, "74s": 0.376, "73s": 0.347,
    "65s": 0.388, "64s": 0.369, "63s": 0.341,
    "54s": 0.359, "53s": 0.341, "52s": 0.321,
    "43s": 0.327, "42s": 0.310,
    "32s": 0.296,
    "AKo": 0.652, "AQo": 0.644, "AJo": 0.633, "ATo": 0.622, "A9o": 0.604,
    "A8o": 0.594, "A7o": 0.584, "A6o": 0.572, "A5o": 0.575, "A4o": 0.567,
    "A3o": 0.558, "A2o": 0.549,
    "KQo": 0.611, "KJo": 0.601, "KTo": 0.589, "K9o": 0.564, "K8o": 0.541,
    "K7o": 0.531, "K6o": 0.520, "K5o": 0.508, "K4o": 0.498, "K3o": 0.489,
    "K2o": 0.480,
    "QJo": 0.580, "QTo": 0.570, "Q9o": 0.546, "Q8o": 0.521,
    "Q7o": 0.499, "Q6o": 0.488, "Q5o": 0.479, "Q4o": 0.468, "Q3o": 0.458, "Q2o": 0.448,
    "JTo": 0.560, "J9o": 0.537, "J8o": 0.512, "J7o": 0.488, "J6o": 0.456,
    "J5o": 0.446, "J4o": 0.436, "J3o": 0.426, "J2o": 0.417,
    "T9o": 0.519, "T8o": 0.495, "T7o": 0.471, "T6o": 0.449, "T5o": 0.415,
    "T4o": 0.406, "T3o": 0.397, "T2o": 0.387,
    "98o": 0.476, "97o": 0.453, "96o": 0.430, "95o": 0.397, "94o": 0.364,
    "87o": 0.434, "86o": 0.412, "85o": 0.379, "84o": 0.348,
    "76o": 0.396, "75o": 0.374, "74o": 0.343,
    "65o": 0.358, "64o": 0.337,
    "54o": 0.327, "53o": 0.308,
    "43o": 0.292,
    "32o": 0.262,
}


def preflop_equity_vs_random(hole: List[str]) -> float:
    return PREFLOP_EQUITY_VS_RANDOM.get(hand_169(hole), 0.45)


def equity_vs_random(hole: List[str], board: List[str], n_villains: int = 1,
                     trials: int = 500, deadline_s: Optional[float] = None) -> float:
    """Adaptive Monte Carlo equity. If no board and HU, uses cached LUT."""
    if not board and n_villains == 1:
        return preflop_equity_vs_random(hole)
    if not _HAS_EVAL7:
        # Coarse fallback: reuse preflop equity, decay slightly with villains
        base = preflop_equity_vs_random(hole)
        return base ** n_villains

    hero = cards_to_eval7(hole)
    board_e = cards_to_eval7(board)
    dead = set(str(c) for c in hero + board_e)
    deck_pool = [c for c in eval7.Deck() if str(c) not in dead]
    cards_to_deal = (5 - len(board)) + 2 * n_villains
    if cards_to_deal > len(deck_pool):
        return 0.5

    wins = ties = 0
    i = 0
    for i in range(trials):
        if deadline_s and time.perf_counter() > deadline_s - 0.05:
            break
        sample = random.sample(deck_pool, cards_to_deal)
        extra_board = sample[:5 - len(board)]
        full_board = board_e + extra_board
        villain_offset = 5 - len(board)
        villains = [sample[villain_offset + 2 * j: villain_offset + 2 * j + 2]
                    for j in range(n_villains)]
        hero_score = eval7.evaluate(hero + full_board)
        villain_scores = [eval7.evaluate(v + full_board) for v in villains]
        best_v = max(villain_scores)
        if hero_score > best_v:
            wins += 1
        elif hero_score == best_v:
            ties += 1

    n = max(i + 1, 1)
    return (wins + 0.5 * ties) / n
